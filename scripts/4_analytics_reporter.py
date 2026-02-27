"""
4_analytics_reporter.py — V2: Fetch GA4 data for READY LPs, analyze with Gemini, generate improvement suggestions.

Data sources (V2):
  - lp_ready_log (READY) → active LP run_ids
  - gate_decision_log (PASS) → market name, payer
  - offer_3_log → offers per run_id
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
    get_all_rows,
    append_rows,
)
from utils.slack_notifier import send_message as slack_notify
from utils.status_writer import update_status
from utils.learning_engine import get_learning_context
from utils.downstream_metrics import aggregate_daily_downstream

logger = get_logger("analytics_reporter", "analytics_reporter.log")

jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

ANALYSIS_DAYS = 7


def _get_ready_markets() -> list[dict]:
    """Build list of active LP markets from V2 sheets.

    Joins lp_ready_log (READY) + gate_decision_log (PASS) + offer_3_log.
    Returns list of dicts with: id, name, payer, offers.
    """
    lp_rows = get_all_rows("lp_ready_log")
    ready_run_ids = {
        r["run_id"] for r in lp_rows
        if r.get("status") == "READY" and r.get("run_id")
    }

    if not ready_run_ids:
        return []

    # Get market details from gate_decision_log
    gate_rows = get_all_rows("gate_decision_log")
    gate_by_run = {}
    for g in gate_rows:
        rid = g.get("run_id", "")
        if rid in ready_run_ids and g.get("status") == "PASS":
            gate_by_run[rid] = g

    # Get offers from offer_3_log
    offer_rows = get_all_rows("offer_3_log")
    offers_by_run: dict[str, list[dict]] = {}
    for o in offer_rows:
        rid = o.get("run_id", "")
        if rid in ready_run_ids:
            offers_by_run.setdefault(rid, []).append(o)

    # Build market entries
    markets = []
    for rid in ready_run_ids:
        gate = gate_by_run.get(rid, {})
        offers = offers_by_run.get(rid, [])

        market_name = gate.get("micro_market", rid[:8])
        payer = gate.get("payer", "")
        if not payer and offers:
            payer = offers[0].get("payer", "")

        markets.append({
            "id": rid,
            "name": market_name,
            "payer": payer,
            "offers": offers[:3],
        })

    return markets


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


def _get_sns_posts_for_market(run_id: str) -> list[dict]:
    """Get recent SNS posts for a market."""
    try:
        all_posts = get_all_rows("sns_posts")
        return [p for p in all_posts if p.get("business_id") == run_id][:5]
    except Exception:
        return []


def analyze_and_suggest(market: dict, metrics: dict, learning_context: str = "") -> list[dict]:
    """Generate improvement suggestions using Gemini."""
    sns_posts = _get_sns_posts_for_market(market["id"])

    # Format offers for the prompt
    offers_text = ""
    for i, o in enumerate(market.get("offers", []), 1):
        offers_text += (
            f"  {i}. {o.get('offer_name', '不明')}"
            f" — {o.get('deliverable', '')} / {o.get('price', '')}\n"
        )

    template = jinja_env.get_template("analysis_prompt.j2")
    prompt = template.render(
        name=market["name"],
        payer=market.get("payer", ""),
        offers_text=offers_text,
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
        max_tokens=4096,
        temperature=0.6,
    )

    if not suggestions:
        logger.warning(f"No suggestions generated for {market.get('name', 'unknown')}")
        return []

    if not isinstance(suggestions, list):
        suggestions = [suggestions]

    return suggestions


def _record_suggestions(run_id: str, suggestions: list[dict]) -> None:
    """Save improvement suggestions to Sheets."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    for s in suggestions:
        rows.append([
            run_id,
            now,
            s.get("suggestion", ""),
            s.get("priority", "medium"),
            "pending",
        ])
    if rows:
        append_rows("improvement_suggestions", rows)
        logger.info(f"Recorded {len(rows)} suggestions for {run_id}")


def main():
    logger.info("=== Analytics reporter start (V2) ===")
    update_status("4_analytics_reporter", "running", "GA4データ取得中...")

    try:
        # V2: Get active markets from lp_ready_log + gate_decision_log
        active_markets = _get_ready_markets()
        if not active_markets:
            logger.info("No READY markets with LPs. Exiting.")
            update_status("4_analytics_reporter", "success", "対象なし", {"suggestions": 0})
            return

        logger.info(f"Found {len(active_markets)} READY markets for analysis")

        # Fetch GA4 metrics for all LPs
        all_metrics = fetch_all_lp_metrics(days=ANALYSIS_DAYS)
        metrics_by_id = {m["business_id"]: m for m in all_metrics}

        # Record to analytics sheet
        _record_analytics(all_metrics)

        # Load learning context for analysis
        learning_context = get_learning_context(categories=["lp_optimization"])

        # Analyze each active market
        update_status("4_analytics_reporter", "running", "Gemini分析中...")
        total_suggestions = 0
        for market in active_markets:
            rid = market["id"]
            metrics = metrics_by_id.get(rid, {
                "pageviews": 0, "sessions": 0,
                "bounce_rate": 0, "avg_time": 0, "conversions": 0,
            })

            logger.info(f"Analyzing {market['name']} ({rid[:8]}): PV={metrics.get('pageviews', 0)}")
            try:
                suggestions = analyze_and_suggest(market, metrics, learning_context=learning_context)
                if suggestions:
                    _record_suggestions(rid, suggestions)
                    total_suggestions += len(suggestions)
            except Exception as e:
                logger.warning(f"Analysis failed for {rid[:8]}: {e}")

        if total_suggestions:
            slack_notify(
                f":bar_chart: 分析完了: *{len(active_markets)}件* のLP分析、"
                f"*{total_suggestions}件* の改善提案を生成しました。"
            )

        # V2: Zero-continuity alert — detect measurement anomalies
        try:
            zero_days = sum(
                1 for m in all_metrics
                if int(m.get("pageviews", 0)) == 0 and int(m.get("sessions", 0)) == 0
            )
            if zero_days >= 3:
                slack_notify(
                    f":rotating_light: *計測異常アラート*\n"
                    f"GA4データが{zero_days}日間連続0です。\n"
                    f"GTM設定・GA4プロパティ・LP URLを確認してください。\n"
                    f":warning: これは正常状態ではありません（正常扱い禁止）"
                )
                logger.warning(f"Zero-continuity alert: {zero_days} consecutive zero days")
        except Exception as ze:
            logger.warning(f"Zero-continuity check failed: {ze}")

        # --- Downstream KPI aggregation ---
        downstream_kpi = {}
        try:
            update_status("4_analytics_reporter", "running", "下流KPI集計中...")
            downstream_kpi = aggregate_daily_downstream()
            logger.info(f"Downstream KPI: inquiries={downstream_kpi.get('total_inquiries', 0)}, "
                        f"deals_won={downstream_kpi.get('deals_won', 0)}, "
                        f"deal_rate={downstream_kpi.get('deal_rate', 0)}")
            if downstream_kpi.get("total_inquiries", 0) > 0:
                slack_notify(
                    f":chart_with_downwards_trend: *下流KPI*: "
                    f"問い合わせ {downstream_kpi['total_inquiries']}件 / "
                    f"成約 {downstream_kpi.get('deals_won', 0)}件 / "
                    f"成約率 {downstream_kpi.get('deal_rate', 0):.1%}"
                )
        except Exception as de:
            logger.warning(f"Downstream KPI aggregation failed: {de}")

        total_pv = sum(m.get("pageviews", 0) for m in all_metrics)
        update_status("4_analytics_reporter", "success", f"{total_suggestions}件提案", {
            "suggestions": total_suggestions,
            "total_pageviews": total_pv,
            "lps_analyzed": len(active_markets),
            "downstream_inquiries": downstream_kpi.get("total_inquiries", 0),
            "downstream_deals_won": downstream_kpi.get("deals_won", 0),
            "downstream_deal_rate": downstream_kpi.get("deal_rate", 0),
        })
        logger.info(f"=== Analytics reporter complete: {total_suggestions} suggestions ===")
    except Exception as e:
        update_status("4_analytics_reporter", "error", str(e))
        logger.error(f"Analytics reporter failed: {e}")
        raise


if __name__ == "__main__":
    main()
