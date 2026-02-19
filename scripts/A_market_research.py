"""
A_market_research.py — Automated market intelligence collection.

Reads target markets from settings, generates structured market research
via Claude API with knowledge base context, saves to market_research sheet.

Schedule: Sunday 20:00 (weekly)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import TEMPLATES_DIR, get_logger
from utils.claude_client import generate_json
from utils.sheets_client import get_all_rows, append_rows, ensure_sheet_exists
from utils.slack_notifier import send_message as slack_notify
from utils.status_writer import update_status
from utils.pdf_knowledge import get_knowledge_summary

logger = get_logger("market_research", "market_research.log")
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


def _load_settings() -> dict:
    rows = get_all_rows("settings")
    return {r["key"]: r["value"] for r in rows}


def _make_market_slug(market_name: str) -> str:
    slug = market_name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    slug = slug.strip("-")
    if not slug or not any(c.isalnum() for c in slug):
        slug = f"market-{abs(hash(market_name)) % 100000:05d}"
    return slug


def _get_existing_research_ids() -> set:
    try:
        rows = get_all_rows("market_research")
        return {r.get("id", "") for r in rows}
    except Exception:
        return set()


def research_market(market_name: str, settings: dict, knowledge_context: str) -> list:
    """Generate comprehensive market research for a single market."""
    segments_per_market = int(settings.get("exploration_segments_per_market", "3"))

    template = jinja_env.get_template("market_research_prompt.j2")
    prompt = template.render(
        market_name=market_name,
        segments_per_market=segments_per_market,
        knowledge_context=knowledge_context,
    )

    result = generate_json(
        prompt=prompt,
        system="あなたは日本市場に精通した市場調査アナリストです。"
               "PEST分析、業界構造分析、TAM/SAM推定に長けています。"
               "必ず指定のJSON配列フォーマットで出力してください。",
        max_tokens=8192,
        temperature=0.5,
    )

    if isinstance(result, dict):
        return [result]
    return result


def save_research_to_sheets(research_list: list, batch_id: str) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []

    for r in research_list:
        slug = _make_market_slug(r.get("market_name", "unknown"))
        key_players = r.get("key_players", [])
        pain_points = r.get("customer_pain_points", [])

        rows.append([
            slug,
            r.get("market_name", ""),
            r.get("industry", ""),
            r.get("market_size_tam", ""),
            r.get("market_size_sam", ""),
            r.get("growth_rate", ""),
            r.get("pest_political", ""),
            r.get("pest_economic", ""),
            r.get("pest_social", ""),
            r.get("pest_technological", ""),
            r.get("industry_structure", ""),
            json.dumps(key_players, ensure_ascii=False) if isinstance(key_players, list) else str(key_players),
            json.dumps(pain_points, ensure_ascii=False) if isinstance(pain_points, list) else str(pain_points),
            r.get("entry_barriers", ""),
            r.get("regulations", ""),
            r.get("data_sources", "Claude知識ベース"),
            r.get("confidence_score", 3),
            "draft",
            batch_id,
            now,
        ])

    if rows:
        append_rows("market_research", rows)
    return len(rows)


def main():
    logger.info("=== Market research start ===")
    update_status("A_market_research", "running", "市場調査を開始...")

    try:
        settings = _load_settings()
        markets_str = settings.get(
            "exploration_markets",
            settings.get("target_industries", "IT,エネルギー"),
        )
        markets = [m.strip() for m in markets_str.split(",") if m.strip()]

        existing_ids = _get_existing_research_ids()
        knowledge_context = get_knowledge_summary()
        batch_id = datetime.now().strftime("%Y-%m-%d")

        all_research = []
        for market in markets:
            slug = _make_market_slug(market)
            # Skip if any segment for this market already exists
            if any(eid.startswith(slug) or eid == slug for eid in existing_ids):
                logger.info(f"Market already researched: {market}, skipping")
                continue

            update_status("A_market_research", "running", f"調査中: {market}")
            logger.info(f"Researching market: {market}")

            segments = research_market(market, settings, knowledge_context)
            all_research.extend(segments)

        count = save_research_to_sheets(all_research, batch_id)

        if count > 0:
            slack_notify(
                f":mag: 市場調査完了: *{count}件* の市場セグメントを調査しました。\n"
                f"対象: {', '.join(markets)}"
            )

        update_status(
            "A_market_research", "success",
            f"{count}セグメント調査完了",
            {"segments_researched": count},
        )
        logger.info(f"=== Market research complete: {count} segments ===")
    except Exception as e:
        update_status("A_market_research", "error", str(e))
        logger.error(f"Market research failed: {e}")
        raise


if __name__ == "__main__":
    main()
