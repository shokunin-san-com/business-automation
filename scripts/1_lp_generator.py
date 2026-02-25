"""
1_lp_generator.py — Generate LP content for active business ideas.

Reads active ideas from Google Sheets, generates LP content via Claude API,
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
from utils.claude_client import generate_json
from utils.sheets_client import (
    get_rows_by_status,
    get_all_rows,
    append_row,
    find_row_index,
    update_cell,
)
from utils.slack_notifier import send_message as slack_notify
from utils.status_writer import update_status
from utils.gcs_client import upload_json as gcs_upload
from utils.pdf_knowledge import get_knowledge_summary
from utils.learning_engine import get_learning_context

logger = get_logger("lp_generator", "lp_generator.log")

jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


def _already_generated(business_id: str) -> bool:
    """Check if LP content already exists for this business idea."""
    json_path = LP_CONTENT_DIR / f"{business_id}.json"
    if json_path.exists():
        return True
    existing = get_all_rows("lp_content")
    return any(r.get("business_id") == business_id for r in existing)


def generate_lp_content(idea: dict, knowledge_context: str = "", learning_context: str = "") -> dict:
    """Generate LP content for a single business idea via Claude."""
    template = jinja_env.get_template("lp_prompt.j2")
    prompt = template.render(
        name=idea["name"],
        category=idea.get("category", ""),
        description=idea.get("description", ""),
        target_audience=idea.get("target_audience", ""),
        market_size=idea.get("market_size", ""),
        differentiator=idea.get("differentiator", ""),
        company_name=YOUR_COMPANY_NAME,
        your_name=YOUR_NAME,
        your_email=YOUR_EMAIL,
        knowledge_context=knowledge_context,
        learning_context=learning_context,
    )

    lp_data = generate_json(
        prompt=prompt,
        system="あなたは日本市場向けLPの専門コピーライターです。指定のJSONフォーマットで正確に出力してください。",
        max_tokens=4096,
        temperature=0.7,
    )

    # Ensure we got a dict back (not a list or empty)
    if isinstance(lp_data, list):
        if len(lp_data) > 0 and isinstance(lp_data[0], dict):
            lp_data = lp_data[0]
        else:
            raise ValueError(f"AI returned a list instead of dict for LP content: {str(lp_data)[:200]}")
    if not isinstance(lp_data, dict):
        raise ValueError(f"AI returned unexpected type {type(lp_data).__name__} for LP content")

    # Add metadata
    lp_data["id"] = idea["id"]
    lp_data["name"] = idea["name"]
    lp_data["category"] = idea.get("category", "")
    lp_data["target_audience"] = idea.get("target_audience", "")

    return lp_data


def save_lp_content(business_id: str, lp_data: dict) -> Path:
    """Save LP content JSON to data/lp_content/ and upload to GCS."""
    json_path = LP_CONTENT_DIR / f"{business_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(lp_data, f, ensure_ascii=False, indent=2)
    logger.info(f"LP content saved: {json_path}")

    # Upload to GCS for cloud access
    gcs_url = gcs_upload(f"lp_content/{business_id}.json", lp_data)
    if gcs_url:
        logger.info(f"LP content uploaded to GCS: {gcs_url}")

    return json_path


def record_to_sheets(business_id: str, lp_data: dict) -> None:
    """Write LP content summary to lp_content sheet."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    row = [
        business_id,
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

    # Update lp_url in business_ideas
    row_idx = find_row_index("business_ideas", "id", business_id)
    if row_idx:
        update_cell("business_ideas", row_idx, 7, f"/lp/{business_id}")
    logger.info(f"LP content recorded to Sheets for {business_id}")


def main():
    logger.info("=== LP generator start ===")
    update_status("1_lp_generator", "running", "LP生成チェック中...")

    try:
        active_ideas = get_rows_by_status("business_ideas", "active")
        if not active_ideas:
            logger.info("No active business ideas found. Exiting.")
            update_status("1_lp_generator", "success", "対象なし", {"lps_generated": 0})
            return

        # Load knowledge context once for all LP generation
        knowledge_context = get_knowledge_summary()

        # Load learning context (AI insights + human directives)
        learning_context = get_learning_context(categories=["lp_optimization"])

        generated_count = 0
        for idea in active_ideas:
            bid = idea["id"]
            if _already_generated(bid):
                logger.info(f"LP already generated for {bid}, skipping")
                continue

            try:
                update_status("1_lp_generator", "running", f"LP生成中: {idea['name']}")
                logger.info(f"Generating LP for: {idea['name']} ({bid})")
                lp_data = generate_lp_content(idea, knowledge_context=knowledge_context, learning_context=learning_context)
                save_lp_content(bid, lp_data)
                record_to_sheets(bid, lp_data)
                generated_count += 1
            except Exception as e:
                logger.error(f"Failed to generate LP for {bid}: {e}", exc_info=True)
                continue

        if generated_count > 0:
            slack_notify(f":rocket: LP を *{generated_count}件* 自動生成しました。数分以内に自動公開されます。")

        update_status("1_lp_generator", "success", f"{generated_count}件生成", {"lps_generated": generated_count})
        logger.info(f"=== LP generator complete: {generated_count} LPs generated ===")
    except Exception as e:
        update_status("1_lp_generator", "error", str(e))
        logger.error(f"LP generator failed: {e}")
        raise


if __name__ == "__main__":
    main()
