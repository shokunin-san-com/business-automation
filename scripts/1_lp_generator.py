"""
1_lp_generator.py — V2: Generate LP content for READY markets.

Reads READY markets from lp_ready_log, joins with gate_decision_log /
offer_3_log / competitor_20_log, generates LP content via Gemini,
saves JSON files to data/lp_content/ and records in Sheets.
"""

import json
import sys
from pathlib import Path
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    TEMPLATES_DIR,
    LP_CONTENT_DIR,
    YOUR_COMPANY_NAME,
    YOUR_NAME,
    YOUR_EMAIL,
    get_logger,
)
from utils.claude_client import generate_json_with_retry
from utils.sheets_client import (
    get_all_rows,
    append_row,
    append_rows,
)
from utils.slack_notifier import send_message as slack_notify
from utils.status_writer import update_status
from utils.gcs_client import upload_json as gcs_upload
from utils.pdf_knowledge import get_knowledge_summary
from utils.learning_engine import get_learning_context

logger = get_logger("lp_generator", "lp_generator.log")

jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


def _get_ready_markets() -> list[dict]:
    """Get READY markets from V2 sheets that don't already have LP content.

    Joins: lp_ready_log (READY) + gate_decision_log (PASS) + offer_3_log + competitor_20_log.
    Excludes markets that already have lp_content records.
    """
    lp_rows = get_all_rows("lp_ready_log")
    ready_run_ids = {
        r["run_id"] for r in lp_rows
        if r.get("status") == "READY" and r.get("run_id")
    }

    if not ready_run_ids:
        return []

    # Check which IDs already have LP content (business_id column may be run_id or market name)
    try:
        existing_lp = get_all_rows("lp_content")
        existing_ids = set()
        for r in existing_lp:
            existing_ids.add(r.get("business_id", ""))
            existing_ids.add(r.get("run_id", ""))
    except Exception:
        existing_ids = set()

    # Also check local files
    for rid in list(ready_run_ids):
        json_path = LP_CONTENT_DIR / f"{rid}.json"
        if json_path.exists():
            existing_ids.add(rid)

    if not ready_run_ids:
        return []

    # Get PASS gates from gate_decision_log (may be multiple per run_id)
    gate_rows = get_all_rows("gate_decision_log")
    gates_by_run: dict[str, list[dict]] = {}
    for g in gate_rows:
        rid = g.get("run_id", "")
        if rid in ready_run_ids and g.get("status") == "PASS":
            gates_by_run.setdefault(rid, []).append(g)

    # Get offers from offer_3_log
    offer_rows = get_all_rows("offer_3_log")
    offers_by_run: dict[str, list[dict]] = {}
    for o in offer_rows:
        rid = o.get("run_id", "")
        if rid in ready_run_ids:
            offers_by_run.setdefault(rid, []).append(o)

    # Get competitor gaps from competitor_20_log
    comp_rows = get_all_rows("competitor_20_log")
    comps_by_run: dict[str, list[dict]] = {}
    for c in comp_rows:
        rid = c.get("run_id", "")
        if rid in ready_run_ids:
            comps_by_run.setdefault(rid, []).append(c)

    # Build market entries — one per PASS gate (not per run_id)
    markets = []
    for rid in ready_run_ids:
        gates = gates_by_run.get(rid, [])
        offers = offers_by_run.get(rid, [])
        comps = comps_by_run.get(rid, [])

        if not gates:
            continue  # No PASS gate → skip

        for gate in gates:
            market_name = gate.get("micro_market", rid[:8])
            # Use market_name as unique LP id (run_id + market)
            lp_id = f"{rid[:8]}_{market_name}"

            # Skip if this specific market already has LP
            if lp_id in existing_ids or market_name in existing_ids:
                continue

            payer = gate.get("payer", "")
            if not payer and offers:
                payer = offers[0].get("payer", "")

            markets.append({
                "run_id": rid,
                "lp_id": lp_id,
                "name": market_name,
                "payer": payer,
                "evidence_urls": gate.get("evidence_urls", ""),
                "blackout_hypothesis": gate.get("blackout_hypothesis", ""),
                "offers": offers[:3],
                "competitors": comps[:20],
            })

    return markets


def generate_lp_content(
    market: dict,
    knowledge_context: str = "",
    learning_context: str = "",
) -> dict:
    """Generate LP content for a V2 market via Gemini."""
    # Format offers
    offers_text = ""
    for i, o in enumerate(market.get("offers", []), 1):
        offers_text += (
            f"  {i}. {o.get('offer_name', '不明')}"
            f" — {o.get('deliverable', '')} / {o.get('price', '')}\n"
            f"     即効性: {o.get('time_to_value', '')} / 代替: {o.get('replaces', '')}\n"
        )

    # Format competitor gaps (top 5)
    gaps_text = ""
    seen_companies = set()
    for c in market.get("competitors", []):
        company = c.get("company_name", "")
        if company in seen_companies:
            continue
        seen_companies.add(company)
        gap = c.get("gap", c.get("weakness", ""))
        if gap:
            gaps_text += f"  - {company}: {gap}\n"
        if len(seen_companies) >= 5:
            break

    template = jinja_env.get_template("lp_prompt.j2")
    prompt = template.render(
        name=market["name"],
        payer=market.get("payer", ""),
        offers_text=offers_text,
        gaps_text=gaps_text,
        evidence_urls=market.get("evidence_urls", ""),
        blackout_hypothesis=market.get("blackout_hypothesis", ""),
        company_name=YOUR_COMPANY_NAME,
        your_name=YOUR_NAME,
        your_email=YOUR_EMAIL,
        knowledge_context=knowledge_context,
        learning_context=learning_context,
    )

    lp_data = generate_json_with_retry(
        prompt=prompt,
        system="あなたは日本市場向けLPの専門コピーライターです。指定のJSONフォーマットで正確に出力してください。",
        max_tokens=8192,
        temperature=0.7,
        max_retries=3,
    )

    # Ensure we got a dict back
    if isinstance(lp_data, list):
        if len(lp_data) > 0 and isinstance(lp_data[0], dict):
            lp_data = lp_data[0]
        else:
            raise ValueError(f"AI returned a list instead of dict: {str(lp_data)[:200]}")
    if not isinstance(lp_data, dict):
        raise ValueError(f"AI returned unexpected type {type(lp_data).__name__}")

    # Add V2 metadata
    lp_data["id"] = market["run_id"]
    lp_data["name"] = market["name"]
    lp_data["payer"] = market.get("payer", "")

    return lp_data


def save_lp_content(run_id: str, lp_data: dict) -> Path:
    """Save LP content JSON to data/lp_content/ and upload to GCS."""
    json_path = LP_CONTENT_DIR / f"{run_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(lp_data, f, ensure_ascii=False, indent=2)
    logger.info(f"LP content saved: {json_path}")

    # Upload to GCS for cloud access
    gcs_url = gcs_upload(f"lp_content/{run_id}.json", lp_data)
    if gcs_url:
        logger.info(f"LP content uploaded to GCS: {gcs_url}")

    return json_path


def record_to_sheets(run_id: str, lp_data: dict) -> None:
    """Write LP content summary to lp_content sheet."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    row = [
        run_id,
        lp_data.get("headline", ""),
        lp_data.get("subheadline", ""),
        json.dumps(lp_data.get("sections", []), ensure_ascii=False),
        lp_data.get("cta_text", ""),
        lp_data.get("meta_description", ""),
        lp_data.get("og_title", ""),
        lp_data.get("og_description", ""),
        now,
    ]
    append_row("lp_content", row)
    logger.info(f"LP content recorded to Sheets for {run_id}")


def main():
    logger.info("=== LP generator start (V2) ===")
    update_status("1_lp_generator", "running", "LP生成チェック中...")

    try:
        # V2: Get READY markets that don't have LP content yet
        ready_markets = _get_ready_markets()
        if not ready_markets:
            logger.info("No READY markets without LP content. Exiting.")
            update_status("1_lp_generator", "success", "対象なし", {"lps_generated": 0})
            return

        logger.info(f"Found {len(ready_markets)} READY markets for LP generation")

        # Load knowledge context once for all LP generation
        knowledge_context = get_knowledge_summary()

        # Load learning context
        learning_context = get_learning_context(categories=["lp_optimization"])

        generated_count = 0
        blog_markets: list[str] = []  # Track markets that need blog generation
        for market in ready_markets:
            rid = market["run_id"]
            market_name = market["name"]
            # Use market name as business_id (LP URL slug)
            business_id = market_name
            try:
                update_status("1_lp_generator", "running", f"LP生成中: {market_name}")
                logger.info(f"Generating LP for: {market_name} ({rid[:8]})")
                lp_data = generate_lp_content(
                    market,
                    knowledge_context=knowledge_context,
                    learning_context=learning_context,
                )
                save_lp_content(business_id, lp_data)
                record_to_sheets(business_id, lp_data)
                generated_count += 1
                blog_markets.append(business_id)
            except Exception as e:
                logger.error(f"Failed to generate LP for {market_name}: {e}", exc_info=True)
                continue

        if generated_count > 0:
            slack_notify(f":rocket: LP を *{generated_count}件* 自動生成しました。数分以内に自動公開されます。")

        # --- Auto-trigger blog generation for new LPs ---
        blog_count = 0
        for business_id in blog_markets:
            try:
                update_status("1_lp_generator", "running", f"ブログ生成中: {business_id[:20]}")
                logger.info(f"Triggering blog generation for: {business_id}")
                from blog_generator import generate_articles
                articles = generate_articles(business_id=business_id)
                blog_count += articles
                logger.info(f"Blog generation complete: {articles} articles for {business_id}")
            except Exception as e:
                logger.error(f"Blog generation failed for {business_id}: {e}", exc_info=True)
                # Blog failure should NOT break LP pipeline
                continue

        total_info = f"LP {generated_count}件"
        if blog_count > 0:
            total_info += f" + ブログ {blog_count}件"

        update_status("1_lp_generator", "success", total_info, {
            "lps_generated": generated_count,
            "blog_articles_generated": blog_count,
        })
        logger.info(f"=== LP generator complete: {generated_count} LPs, {blog_count} blog articles ===")
    except Exception as e:
        update_status("1_lp_generator", "error", str(e))
        logger.error(f"LP generator failed: {e}")
        raise


if __name__ == "__main__":
    main()
