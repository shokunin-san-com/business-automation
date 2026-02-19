"""
C_competitor_analysis.py — Analyze competitors in selected markets.

Reads approved markets from market_selection (status=selected),
identifies and analyzes competitors, outputs gap analysis
that feeds into idea generation.

Schedule: Monday 4:00 (after market selection approval)
"""
from __future__ import annotations

import json
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

logger = get_logger("competitor_analysis", "competitor_analysis.log")
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


def _load_settings() -> dict:
    rows = get_all_rows("settings")
    return {r["key"]: r["value"] for r in rows}


def _get_selected_markets() -> list:
    """Get markets approved for competitor analysis."""
    try:
        rows = get_all_rows("market_selection")
        return [r for r in rows if r.get("status") == "selected"]
    except Exception:
        return []


def _get_market_research(market_research_id: str) -> dict | None:
    """Fetch the original market research row for enriched context."""
    try:
        rows = get_all_rows("market_research")
        for r in rows:
            if r.get("id") == market_research_id:
                return r
    except Exception:
        pass
    return None


def _already_analyzed(market_selection_id: str) -> bool:
    try:
        rows = get_all_rows("competitor_analysis")
        return any(r.get("market_selection_id") == market_selection_id for r in rows)
    except Exception:
        return False


def analyze_competitors(
    market_selection: dict,
    market_research: dict | None,
    settings: dict,
    knowledge_context: str,
) -> list:
    """Generate competitor analysis for a selected market."""
    competitors_count = int(settings.get("competitors_per_market", "5"))

    research_context = {}
    if market_research:
        for k in ["market_size_tam", "market_size_sam", "industry_structure",
                   "key_players", "customer_pain_points", "entry_barriers"]:
            research_context[k] = market_research.get(k, "")

    template = jinja_env.get_template("competitor_analysis_prompt.j2")
    prompt = template.render(
        market_name=market_selection.get("market_name", ""),
        entry_angle=market_selection.get("recommended_entry_angle", ""),
        pest_summary=market_selection.get("pest_summary", ""),
        five_forces_summary=market_selection.get("five_forces_summary", ""),
        market_research=json.dumps(research_context, ensure_ascii=False),
        competitors_count=competitors_count,
        knowledge_context=knowledge_context,
    )

    result = generate_json(
        prompt=prompt,
        system="あなたは競合分析の専門家です。客観的かつ具体的に競合を分析し、"
               "参入機会とギャップを特定してください。"
               "必ず指定のJSON配列フォーマットで出力してください。",
        max_tokens=8192,
        temperature=0.4,
    )

    if isinstance(result, dict):
        return [result]
    return result


def save_analysis_to_sheets(
    analysis_rows: list,
    market_selection_id: str,
    market_name: str,
) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []

    for comp in analysis_rows:
        comp_name = comp.get("competitor_name", "unknown")
        safe_name = comp_name[:20].replace(" ", "-")
        gap_opps = comp.get("gap_opportunities", [])

        rows.append([
            f"comp-{market_selection_id}-{safe_name}",
            market_selection_id,
            market_name,
            comp_name,
            comp.get("competitor_url", ""),
            comp.get("competitor_type", "direct"),
            comp.get("product_service", ""),
            comp.get("pricing_model", ""),
            comp.get("target_segment", ""),
            comp.get("strengths", ""),
            comp.get("weaknesses", ""),
            comp.get("market_share_estimate", ""),
            comp.get("differentiation", ""),
            json.dumps(gap_opps, ensure_ascii=False) if isinstance(gap_opps, list) else str(gap_opps),
            now,
        ])

    if rows:
        append_rows("competitor_analysis", rows)
    return len(rows)


def main():
    logger.info("=== Competitor analysis start ===")
    update_status("C_competitor_analysis", "running", "競合調査を開始...")

    try:
        settings = _load_settings()
        knowledge_context = get_knowledge_summary()

        selected_markets = _get_selected_markets()
        if not selected_markets:
            logger.info("No selected markets found. Exiting.")
            update_status("C_competitor_analysis", "success", "承認済み市場なし",
                          {"competitors_analyzed": 0})
            return

        total_competitors = 0

        for market in selected_markets:
            sel_id = market.get("id", "")
            if _already_analyzed(sel_id):
                logger.info(f"Already analyzed: {market.get('market_name')}, skipping")
                continue

            market_name = market.get("market_name", "")
            update_status("C_competitor_analysis", "running", f"競合分析中: {market_name}")
            logger.info(f"Analyzing competitors in: {market_name}")

            research = _get_market_research(market.get("market_research_id", ""))
            competitors = analyze_competitors(market, research, settings, knowledge_context)

            count = save_analysis_to_sheets(competitors, sel_id, market_name)
            total_competitors += count
            logger.info(f"Analyzed {count} competitors in {market_name}")

        if total_competitors > 0:
            slack_notify(
                f":crossed_swords: 競合調査完了: "
                f"*{len(selected_markets)}市場* で *{total_competitors}社* を分析しました。\n"
                f"次回のアイデア生成に反映されます。"
            )

        update_status(
            "C_competitor_analysis", "success",
            f"{total_competitors}社の競合を分析",
            {"competitors_analyzed": total_competitors,
             "markets_processed": len(selected_markets)},
        )
        logger.info(f"=== Competitor analysis complete: {total_competitors} competitors ===")
    except Exception as e:
        update_status("C_competitor_analysis", "error", str(e))
        logger.error(f"Competitor analysis failed: {e}")
        raise


if __name__ == "__main__":
    main()
