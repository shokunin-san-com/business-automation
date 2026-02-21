"""
B_market_selection.py — Score and rank markets for strategic selection.

Reads market_research data, applies PEST + 5-Forces + 5-axis scoring matrix,
outputs ranked markets to market_selection sheet with approval workflow.

Schedule: Sunday 22:00 (weekly, 2h after A_market_research)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import TEMPLATES_DIR, GOOGLE_SHEETS_ID, get_logger
from utils.claude_client import generate_json
from utils.sheets_client import get_all_rows, append_rows, ensure_sheet_exists
from utils.slack_notifier import send_message as slack_notify
from utils.status_writer import update_status
from utils.pdf_knowledge import get_knowledge_summary

logger = get_logger("market_selection", "market_selection.log")
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


def _load_settings() -> dict:
    rows = get_all_rows("settings")
    return {r["key"]: r["value"] for r in rows}


def _get_unscored_research() -> list:
    """Get market_research rows that have not been scored yet."""
    research_rows = get_all_rows("market_research")
    try:
        selection_rows = get_all_rows("market_selection")
        scored_ids = {r.get("market_research_id", "") for r in selection_rows}
    except Exception:
        scored_ids = set()

    return [
        r for r in research_rows
        if r.get("id") and r["id"] not in scored_ids and r.get("status") != "archived"
    ]


BATCH_SIZE = 5  # Process markets in batches to avoid token limit


def score_markets(research_rows: list, settings: dict, knowledge_context: str) -> list:
    """Use Claude to score each market on the 5-axis matrix.

    Processes in batches of BATCH_SIZE to stay within token limits.
    """
    weights_str = settings.get(
        "exploration_scoring_weights",
        '{"distortion":3,"barrier":2,"bpo":2,"growth":1.5,"capability":1.5}',
    )
    weights = json.loads(weights_str)

    all_summaries = []
    for r in research_rows:
        all_summaries.append({
            "id": r.get("id", ""),
            "market_name": r.get("market_name", ""),
            "industry": r.get("industry", ""),
            "market_size_tam": r.get("market_size_tam", ""),
            "growth_rate": r.get("growth_rate", ""),
            "pest_political": r.get("pest_political", ""),
            "pest_economic": r.get("pest_economic", ""),
            "pest_social": r.get("pest_social", ""),
            "pest_technological": r.get("pest_technological", ""),
            "industry_structure": r.get("industry_structure", ""),
            "customer_pain_points": r.get("customer_pain_points", ""),
            "entry_barriers": r.get("entry_barriers", ""),
        })

    # Process in batches
    all_results = []
    template = jinja_env.get_template("market_selection_prompt.j2")
    system_msg = (
        "あなたは事業戦略コンサルタントです。PEST分析、ポーターの5フォース分析、"
        "市場スコアリングに精通しています。厳密かつ合理的に市場を評価してください。"
        "必ず指定のJSON配列フォーマットで出力してください。"
    )

    for i in range(0, len(all_summaries), BATCH_SIZE):
        batch = all_summaries[i : i + BATCH_SIZE]
        logger.info(f"Scoring batch {i // BATCH_SIZE + 1}: {len(batch)} markets")

        prompt = template.render(
            market_summaries=json.dumps(batch, ensure_ascii=False),
            weights=json.dumps(weights, ensure_ascii=False),
            knowledge_context=knowledge_context,
        )

        result = generate_json(
            prompt=prompt,
            system=system_msg,
            max_tokens=16384,
            temperature=0.3,
        )

        if isinstance(result, list):
            all_results.extend(result)
        else:
            logger.warning(f"Unexpected result type from batch: {type(result)}")

    return all_results


def save_selections_to_sheets(selections: list, batch_id: str, top_n: int = 3) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []

    for i, s in enumerate(selections):
        status = "pending_review" if i < top_n else "scored"
        rows.append([
            f"sel-{s.get('market_research_id', 'unknown')}-{batch_id}",
            s.get("market_research_id", ""),
            s.get("market_name", ""),
            s.get("score_distortion_depth", 0),
            s.get("score_entry_barrier", 0),
            s.get("score_bpo_feasibility", 0),
            s.get("score_growth", 0),
            s.get("score_capability_fit", 0),
            s.get("total_score", 0),
            i + 1,  # rank
            s.get("pest_summary", ""),
            s.get("five_forces_summary", ""),
            s.get("rationale", ""),
            s.get("recommended_entry_angle", ""),
            status,
            "",  # reviewed_by
            batch_id,
            now,
        ])

    if rows:
        append_rows("market_selection", rows)
    return len(rows)


def notify_slack_approval(selections: list, top_n: int) -> None:
    dashboard_url = "https://lp-app-smoky.vercel.app/dashboard"
    top_markets = selections[:top_n]

    lines = [
        ":bar_chart: *市場選定結果* — 上位市場の承認をお願いします",
        "",
    ]
    for i, s in enumerate(top_markets):
        lines.append(
            f"*{i+1}. {s.get('market_name', '')}* "
            f"(スコア: {s.get('total_score', 0)}/100)\n"
            f"  推奨参入角度: {str(s.get('recommended_entry_angle', ''))[:80]}"
        )

    lines.extend([
        "",
        f"<{dashboard_url}|ダッシュボードで確認・承認>",
    ])

    slack_notify("\n".join(lines))


def main():
    logger.info("=== Market selection start ===")
    update_status("B_market_selection", "running", "市場選定スコアリング開始...")

    try:
        settings = _load_settings()
        top_n = int(settings.get("selection_top_n", "3"))
        knowledge_context = get_knowledge_summary()
        batch_id = datetime.now().strftime("%Y-%m-%d")

        unscored = _get_unscored_research()
        if not unscored:
            logger.info("No unscored market research found. Exiting.")
            update_status("B_market_selection", "success", "新規対象なし",
                          {"markets_scored": 0})
            return

        update_status("B_market_selection", "running",
                      f"{len(unscored)}市場をスコアリング中...")
        selections = score_markets(unscored, settings, knowledge_context)

        # Sort by total_score descending
        selections.sort(key=lambda x: float(x.get("total_score", 0)), reverse=True)

        count = save_selections_to_sheets(selections, batch_id, top_n=top_n)

        if count > 0:
            notify_slack_approval(selections, top_n)

        update_status(
            "B_market_selection", "success",
            f"{count}市場スコアリング完了（上位{top_n}件を承認待ち）",
            {"markets_scored": count, "top_n": top_n},
        )
        logger.info(f"=== Market selection complete: {count} markets scored ===")
    except Exception as e:
        update_status("B_market_selection", "error", str(e))
        logger.error(f"Market selection failed: {e}")
        raise


if __name__ == "__main__":
    main()
