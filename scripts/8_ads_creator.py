"""
8_ads_creator.py — Auto-create Google Ads search campaigns from business ideas.

Pipeline:
1. Read approved business ideas that have LPs but no ad campaign yet
2. Generate ad copy + keywords via AI (ads_campaign_prompt.j2)
3. Create campaign in PAUSED state via Google Ads API
4. Record to ads_campaigns sheet
5. Send Slack approval request
"""

import sys
import json
from pathlib import Path
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import TEMPLATES_DIR, get_logger
from utils.claude_client import generate_json
from utils.sheets_client import get_all_rows, append_row
from utils.google_ads_client import create_search_campaign
from utils.slack_notifier import send_message as slack_notify
from utils.status_writer import update_status

try:
    from utils.learning_engine import get_learning_context
except ImportError:
    def get_learning_context(*_a, **_kw):
        return ""

logger = get_logger("ads_creator", "ads_creator.log")

jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

DEFAULT_BUDGET = 3000  # yen per day


def _get_target_ideas() -> list[dict]:
    """Find approved ideas with LPs that don't have ad campaigns yet."""
    ideas = get_all_rows("business_ideas")
    approved = [
        i for i in ideas
        if i.get("status") == "approved" and i.get("lp_url")
    ]

    # Check existing campaigns
    try:
        campaigns = get_all_rows("ads_campaigns")
        existing_bids = {c.get("business_id") for c in campaigns if c.get("status") in ("pending", "active")}
    except Exception:
        existing_bids = set()

    return [i for i in approved if i.get("id") not in existing_bids]


def _generate_ad_content(idea: dict, learning_context: str) -> dict:
    """Generate ad copy and keywords via AI."""
    template = jinja_env.get_template("ads_campaign_prompt.j2")
    prompt = template.render(
        business_name=idea.get("name", ""),
        category=idea.get("category", ""),
        target_audience=idea.get("target_audience", ""),
        description=idea.get("description", ""),
        differentiator=idea.get("differentiator", ""),
        lp_url=idea.get("lp_url", ""),
        learning_context=learning_context,
    )

    result = generate_json(
        prompt=prompt,
        system="あなたはGoogle検索広告の専門家です。高CTRを実現する広告コピーを生成してください。",
        max_tokens=4096,
        temperature=0.7,
    )

    return result if isinstance(result, dict) else {}


def _record_campaign(
    business_id: str,
    campaign_name: str,
    campaign_id: str,
    daily_budget: int,
    ad_content: dict,
) -> None:
    """Record the created campaign to ads_campaigns sheet."""
    now = datetime.now().isoformat()
    append_row("ads_campaigns", [
        f"ads_{business_id}_{datetime.now().strftime('%Y%m%d%H%M')}",  # id
        business_id,
        campaign_name,
        campaign_id,
        "pending",  # status — awaiting human approval
        str(daily_budget),
        json.dumps(ad_content.get("keywords", []), ensure_ascii=False),
        json.dumps({
            "headlines": ad_content.get("headlines", []),
            "descriptions": ad_content.get("descriptions", []),
        }, ensure_ascii=False),
        now,  # created_at
        "",   # activated_at
        "",   # performance_json
    ])


def main():
    logger.info("=== Ads creator start ===")
    update_status("8_ads_creator", "running", "対象事業案を確認中...")

    try:
        # Get default budget from settings
        settings = {r["key"]: r["value"] for r in get_all_rows("settings")}
        budget_str = settings.get("ads_daily_budget", "")
        default_budget = int(budget_str) if budget_str else DEFAULT_BUDGET

        # Get target ideas
        ideas = _get_target_ideas()
        if not ideas:
            logger.info("No ideas eligible for ad campaign creation.")
            update_status("8_ads_creator", "success", "対象事業案なし")
            return

        update_status("8_ads_creator", "running", f"{len(ideas)}件の事業案を処理中...")
        learning_context = get_learning_context(categories=["lp_optimization", "general"])

        created = 0
        for idea in ideas:
            bid = idea.get("id", "unknown")
            name = idea.get("name", "unknown")
            logger.info(f"Processing: {name} ({bid})")

            # 1. Generate ad content
            update_status("8_ads_creator", "running", f"広告テキスト生成中: {name}")
            ad_content = _generate_ad_content(idea, learning_context)

            if not ad_content or not ad_content.get("headlines"):
                logger.warning(f"Failed to generate ad content for {name}")
                continue

            # 2. Determine budget
            suggested = ad_content.get("suggested_budget_yen", default_budget)
            budget = min(int(suggested), default_budget)

            # 3. Create campaign via Google Ads API
            campaign_name = f"BVA_{name}_{datetime.now().strftime('%m%d')}"
            update_status("8_ads_creator", "running", f"キャンペーン作成中: {campaign_name}")

            result = create_search_campaign(
                name=campaign_name,
                daily_budget_yen=budget,
                keywords=ad_content.get("keywords", []),
                negative_keywords=ad_content.get("negative_keywords", []),
                headlines=ad_content.get("headlines", []),
                descriptions=ad_content.get("descriptions", []),
            )

            if not result:
                logger.warning(f"Campaign creation failed for {name}")
                continue

            # 4. Record to sheet
            _record_campaign(
                business_id=bid,
                campaign_name=campaign_name,
                campaign_id=result.get("campaign_id", ""),
                daily_budget=budget,
                ad_content=ad_content,
            )

            # 5. Slack notification
            headlines_preview = "\n".join(f"  - {h}" for h in ad_content.get("headlines", [])[:3])
            keywords_preview = ", ".join(ad_content.get("keywords", [])[:5])
            slack_notify(
                f":mega: *広告キャンペーン作成（承認待ち）*\n"
                f"事業: {name}\n"
                f"キャンペーン: {campaign_name}\n"
                f"日次予算: {budget}円\n"
                f"見出しプレビュー:\n{headlines_preview}\n"
                f"キーワード: {keywords_preview}\n\n"
                f"ダッシュボードで承認してください。"
            )

            created += 1
            logger.info(f"Campaign created: {campaign_name} (PAUSED)")

        update_status("8_ads_creator", "success", f"{created}件のキャンペーン作成", {
            "campaigns_created": created,
            "ideas_checked": len(ideas),
        })
        logger.info(f"=== Ads creator complete: {created} campaigns created ===")

    except Exception as e:
        update_status("8_ads_creator", "error", str(e))
        logger.error(f"Ads creator failed: {e}")
        raise


if __name__ == "__main__":
    main()
