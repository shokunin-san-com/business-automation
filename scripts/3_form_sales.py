"""
3_form_sales.py — Automated form-based outreach.

Pipeline:
1. Scrape target companies (or read from Sheets)
2. Generate personalized sales messages via Claude API
3. Submit via Playwright (with dry-run mode)
4. Record results to Google Sheets
"""


from __future__ import annotations
import asyncio
import sys
from pathlib import Path
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    TEMPLATES_DIR,
    YOUR_COMPANY_NAME,
    YOUR_NAME,
    YOUR_EMAIL,
    get_logger,
)
from utils.claude_client import generate_text
from utils.sheets_client import (
    get_rows_by_status,
    get_all_rows,
    append_row,
    find_row_index,
    update_cell,
)
from utils.scraper import scrape_companies
from utils.form_submitter import submit_form
from utils.slack_notifier import send_message as slack_notify
from utils.status_writer import update_status
from utils.risk_scorer import evaluate as evaluate_risk
from utils.learning_engine import get_learning_context

logger = get_logger("form_sales", "form_sales.log")

jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

# Risk-based auto-decision: low risk → auto-send, high risk → human review
# DRY_RUN overrides risk decision when True
DRY_RUN = False


def _load_settings() -> dict:
    rows = get_all_rows("settings")
    return {r["key"]: r["value"] for r in rows}


def _get_unsent_targets() -> list[dict]:
    """Get form_sales_targets that haven't been contacted yet."""
    rows = get_all_rows("form_sales_targets")
    return [r for r in rows if r.get("status") in ("", "pending", "new")]


def scrape_and_register(idea: dict, max_per_idea: int = 5) -> int:
    """Scrape companies for a business idea and register in Sheets.

    Returns number of new companies added.
    """
    target_audience = idea.get("target_audience", "")
    category = idea.get("category", "")
    query_terms = [category, target_audience]

    existing_urls = {r["url"] for r in get_all_rows("form_sales_targets")}
    added = 0

    companies = scrape_companies(
        industry=category,
        region="",
        max_results=max_per_idea,
    )

    for company in companies:
        if company["url"] in existing_urls:
            continue
        if not company["form_url"]:
            continue

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        append_row("form_sales_targets", [
            idea["id"],
            company["company_name"],
            company["url"],
            company["form_url"],
            company["industry"],
            company.get("region", ""),
            "",  # message (filled later)
            "pending",
            "",  # contacted_at
            "",  # response
        ])
        added += 1

    logger.info(f"Registered {added} new companies for {idea['id']}")
    return added


def generate_sales_message(idea: dict, target: dict, learning_context: str = "", settings: dict | None = None) -> str:
    """Generate a personalized sales message using Claude API."""
    # Use settings from Sheets if available, fall back to env vars
    s = settings or {}
    sender_company = s.get("sender_company", "") or YOUR_COMPANY_NAME
    sender_name = s.get("sender_name", "") or YOUR_NAME
    sender_email = s.get("sender_email", "") or YOUR_EMAIL

    template = jinja_env.get_template("sales_message_prompt.j2")
    prompt = template.render(
        service_name=idea["name"],
        service_description=idea.get("description", ""),
        target_audience=idea.get("target_audience", ""),
        differentiator=idea.get("differentiator", ""),
        company_name=target["company_name"],
        industry=target.get("industry", ""),
        company_url=target["url"],
        sender_company=sender_company,
        sender_name=sender_name,
        sender_email=sender_email,
        learning_context=learning_context,
    )

    return generate_text(
        prompt=prompt,
        system="あなたは日本のBtoB営業メッセージの専門家です。",
        max_tokens=1024,
        temperature=0.7,
    )


async def process_targets(
    idea: dict,
    targets: list[dict],
    daily_limit: int = 5,
    learning_context: str = "",
    settings: dict | None = None,
) -> dict:
    """Generate messages, evaluate risk, and submit forms.

    Returns {"sent": N, "reviewed": N, "blocked": N}.
    """
    counts = {"sent": 0, "reviewed": 0, "blocked": 0}

    for target in targets[:daily_limit]:
        if target.get("business_id") != idea["id"]:
            continue
        if not target.get("form_url"):
            continue

        # Generate message
        logger.info(f"Generating message for {target['company_name']}")
        message = generate_sales_message(idea, target, learning_context=learning_context, settings=settings)

        # Update message in Sheets
        row_idx = find_row_index("form_sales_targets", "form_url", target["form_url"])
        if row_idx:
            update_cell("form_sales_targets", row_idx, 7, message)

        # Risk evaluation
        risk = evaluate_risk(
            text=message,
            platform="form",
            context=f"Sales form for {target['company_name']}",
            use_ai=True,
        )

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        if risk.decision == "block":
            logger.warning(f"BLOCKED: risk={risk.score} for {target['company_name']}")
            if row_idx:
                update_cell("form_sales_targets", row_idx, 8, "blocked")
                update_cell("form_sales_targets", row_idx, 9, now)
            slack_notify(
                f":no_entry: フォーム営業ブロック（リスク {risk.score}）\n"
                f"企業: {target['company_name']}\n理由: {risk.detail}"
            )
            counts["blocked"] += 1
            continue

        if risk.decision == "review":
            logger.info(f"REVIEW: risk={risk.score} for {target['company_name']}")
            if row_idx:
                update_cell("form_sales_targets", row_idx, 8, "pending_review")
                update_cell("form_sales_targets", row_idx, 9, now)
            slack_notify(
                f":warning: フォーム営業 *要確認*（リスク {risk.score}）\n"
                f"企業: {target['company_name']}\n理由: {risk.detail}"
            )
            counts["reviewed"] += 1
            continue

        # Auto-send (risk.decision == "auto")
        if DRY_RUN:
            logger.info(f"DRY_RUN: would send to {target['company_name']} (risk={risk.score})")
            if row_idx:
                update_cell("form_sales_targets", row_idx, 8, "dry_run")
                update_cell("form_sales_targets", row_idx, 9, now)
            counts["sent"] += 1
            continue

        logger.info(f"AUTO-SEND: risk={risk.score} → submitting to {target['company_name']}")
        result = await submit_form(
            form_url=target["form_url"],
            message=message,
            dry_run=False,
        )

        status = result["status"]
        if row_idx:
            update_cell("form_sales_targets", row_idx, 8, status)
            update_cell("form_sales_targets", row_idx, 9, now)

        counts["sent"] += 1
        logger.info(f"Result: {result['status']} — {result['detail']}")

    return counts


def main():
    logger.info("=== Form sales start ===")
    update_status("3_form_sales", "running", "フォーム営業準備中...")

    try:
        settings = _load_settings()
        daily_limit = int(settings.get("form_sales_per_day", "5"))

        active_ideas = get_rows_by_status("business_ideas", "active")
        if not active_ideas:
            logger.info("No active ideas. Exiting.")
            update_status("3_form_sales", "success", "対象なし", {"submitted": 0})
            return

        # Step 1: Scrape new companies for each idea
        update_status("3_form_sales", "running", "企業スクレイピング中...")
        for idea in active_ideas:
            scrape_and_register(idea, max_per_idea=daily_limit)

        # Load learning context for sales messages
        learning_context = get_learning_context(categories=["form_sales"])

        # Step 2: Process pending targets with risk scoring
        update_status("3_form_sales", "running", "リスク評価・フォーム送信中...")
        targets = _get_unsent_targets()
        totals = {"sent": 0, "reviewed": 0, "blocked": 0}

        for idea in active_ideas:
            result = asyncio.run(process_targets(idea, targets, daily_limit, learning_context=learning_context, settings=settings))
            for k in totals:
                totals[k] += result.get(k, 0)

        summary_parts = []
        if totals["sent"]:
            summary_parts.append(f"送信 {totals['sent']}件")
        if totals["reviewed"]:
            summary_parts.append(f"要確認 {totals['reviewed']}件")
        if totals["blocked"]:
            summary_parts.append(f"ブロック {totals['blocked']}件")

        if any(totals.values()):
            slack_notify(f":envelope: フォーム営業: {' / '.join(summary_parts)}")

        update_status("3_form_sales", "success", " / ".join(summary_parts) or "対象なし", totals)
        logger.info(f"=== Form sales complete: {totals} ===")
    except Exception as e:
        update_status("3_form_sales", "error", str(e))
        logger.error(f"Form sales failed: {e}")
        raise


if __name__ == "__main__":
    main()
