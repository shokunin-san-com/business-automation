"""
4_analytics_reporter.py — Fetch GA4 data, analyze with Claude, generate improvement suggestions.
"""

import sys
from pathlib import Path
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import TEMPLATES_DIR, get_logger
from utils.claude_client import generate_json
from utils.ga4_client import fetch_all_lp_metrics
from utils.sheets_client import (
    get_rows_by_status,
    get_all_rows,
    append_row,
    append_rows,
)
from utils.slack_notifier import send_message as slack_notify
from utils.status_writer import update_status
from utils.learning_engine import get_learning_context

logger = get_logger("analytics_reporter", "analytics_reporter.log")

jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

ANALYSIS_DAYS = 7


def _record_analytics(metrics: list[dict]) -> None:
    """Save daily metrics to the analytics sheet."""
    today = datetime.now().strftime("%Y-%m-%d")
    rows = []
    for m in metrics:
        rows.append([
            m["business_id"],
            today,
            m["pageviews"],
            m["sessions"],
            round(m["bounce_rate"], 2),
            m["conversions"],
            round(m["avg_time"], 1),
        ])
    if rows:
        append_rows("analytics", rows)
        logger.info(f"Recorded analytics for {len(rows)} LPs")


def _get_sns_posts_for_idea(business_id: str) -> list[dict]:
    """Get recent SNS posts for a business idea."""
    all_posts = get_all_rows("sns_posts")
    return [p for p in all_posts if p.get("business_id") == business_id][:5]


def analyze_and_suggest(idea: dict, metrics: dict, learning_context: str = "") -> list[dict]:
    """Generate improvement suggestions using Claude API."""
    sns_posts = _get_sns_posts_for_idea(idea["id"])

    template = jinja_env.get_template("analysis_prompt.j2")
    prompt = template.render(
        name=idea["name"],
        category=idea.get("category", ""),
        target_audience=idea.get("target_audience", ""),
        days=ANALYSIS_DAYS,
        pageviews=metrics.get("pageviews", 0),
        sessions=metrics.get("sessions", 0),
        bounce_rate=round(metrics.get("bounce_rate", 0), 1),
        avg_time=round(metrics.get("avg_time", 0), 1),
        conversions=metrics.get("conversions", 0),
        sns_posts=sns_posts,
        learning_context=learning_context,
    )

    suggestions = generate_json(
        prompt=prompt,
        system="あなたはデジタルマーケティング分析の専門家です。データに基づく具体的な提案を行ってください。",
        max_tokens=2048,
        temperature=0.6,
    )

    if not suggestions:
        logger.warning(f"No suggestions generated for {idea.get('name', 'unknown')}")
        return []

    if not isinstance(suggestions, list):
        suggestions = [suggestions]

    return suggestions


def _record_suggestions(business_id: str, suggestions: list[dict]) -> None:
    """Save improvement suggestions to Sheets."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    for s in suggestions:
        rows.append([
            business_id,
            now,
            s.get("suggestion", ""),
            s.get("priority", "medium"),
            "pending",
        ])
    if rows:
        append_rows("improvement_suggestions", rows)
        logger.info(f"Recorded {len(rows)} suggestions for {business_id}")


def main():
    logger.info("=== Analytics reporter start ===")
    update_status("4_analytics_reporter", "running", "GA4データ取得中...")

    try:
        active_ideas = get_rows_by_status("business_ideas", "active")
        if not active_ideas:
            logger.info("No active ideas. Exiting.")
            update_status("4_analytics_reporter", "success", "対象なし", {"suggestions": 0})
            return

        # Fetch GA4 metrics for all LPs
        all_metrics = fetch_all_lp_metrics(days=ANALYSIS_DAYS)
        metrics_by_id = {m["business_id"]: m for m in all_metrics}

        # Record to analytics sheet
        _record_analytics(all_metrics)

        # Load learning context for analysis
        learning_context = get_learning_context(categories=["lp_optimization"])

        # Analyze each active idea
        update_status("4_analytics_reporter", "running", "Claude分析中...")
        total_suggestions = 0
        for idea in active_ideas:
            bid = idea["id"]
            metrics = metrics_by_id.get(bid, {
                "pageviews": 0, "sessions": 0,
                "bounce_rate": 0, "avg_time": 0, "conversions": 0,
            })

            logger.info(f"Analyzing {bid}: PV={metrics.get('pageviews', 0)}")
            try:
                suggestions = analyze_and_suggest(idea, metrics, learning_context=learning_context)
                if suggestions:
                    _record_suggestions(bid, suggestions)
                    total_suggestions += len(suggestions)
            except Exception as e:
                logger.warning(f"Analysis failed for {bid}: {e}")

        if total_suggestions:
            slack_notify(
                f":bar_chart: 分析完了: *{len(active_ideas)}件* のLP分析、"
                f"*{total_suggestions}件* の改善提案を生成しました。"
            )

        total_pv = sum(m.get("pageviews", 0) for m in all_metrics)
        update_status("4_analytics_reporter", "success", f"{total_suggestions}件提案", {
            "suggestions": total_suggestions,
            "total_pageviews": total_pv,
            "lps_analyzed": len(active_ideas),
        })
        logger.info(f"=== Analytics reporter complete: {total_suggestions} suggestions ===")
    except Exception as e:
        update_status("4_analytics_reporter", "error", str(e))
        logger.error(f"Analytics reporter failed: {e}")
        raise


if __name__ == "__main__":
    main()
