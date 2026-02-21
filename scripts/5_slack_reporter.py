"""
5_slack_reporter.py — Daily summary report to Slack.

Aggregates yesterday's data from all Google Sheets and sends a formatted report.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import GOOGLE_SHEETS_ID, get_logger
from utils.sheets_client import get_all_rows, get_rows_by_status, get_sheet_urls
from utils.slack_notifier import send_message as slack_notify
from utils.status_writer import update_status
from utils.learning_engine import detect_trends, get_learning_context

logger = get_logger("slack_reporter", "slack_reporter.log")


def _get_daily_analytics() -> dict[str, dict]:
    """Aggregate analytics data for yesterday by business_id."""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    rows = get_all_rows("analytics")

    agg = defaultdict(lambda: {
        "pageviews": 0, "sessions": 0, "conversions": 0,
        "bounce_rates": [], "avg_times": [],
    })

    for r in rows:
        if str(r.get("date", "")).startswith(yesterday):
            bid = r["business_id"]
            agg[bid]["pageviews"] += int(r.get("pageviews", 0))
            agg[bid]["sessions"] += int(r.get("sessions", 0))
            agg[bid]["conversions"] += int(r.get("conversions", 0))
            br = r.get("bounce_rate")
            if br:
                agg[bid]["bounce_rates"].append(float(br))
            at = r.get("avg_time")
            if at:
                agg[bid]["avg_times"].append(float(at))

    # Calculate averages
    result = {}
    for bid, data in agg.items():
        brs = data["bounce_rates"]
        ats = data["avg_times"]
        result[bid] = {
            "pageviews": data["pageviews"],
            "sessions": data["sessions"],
            "conversions": data["conversions"],
            "bounce_rate": round(sum(brs) / len(brs), 1) if brs else 0,
            "avg_time": round(sum(ats) / len(ats), 1) if ats else 0,
        }

    return result


def _count_daily_sns_posts() -> dict[str, int]:
    """Count SNS posts per business_id for yesterday."""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    rows = get_all_rows("sns_posts")
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        if str(r.get("posted_at", "")).startswith(yesterday):
            counts[r["business_id"]] += 1
    return dict(counts)


def _count_daily_form_submissions() -> dict[str, int]:
    """Count form submissions per business_id for yesterday."""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    rows = get_all_rows("form_sales_targets")
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        if str(r.get("contacted_at", "")).startswith(yesterday) and r.get("status") in ("success", "sent", "dry_run"):
            counts[r.get("business_id", "")] += 1
    return dict(counts)


def _get_top_suggestions() -> list[dict]:
    """Get high-priority pending suggestions."""
    rows = get_all_rows("improvement_suggestions")
    return [
        r for r in rows
        if r.get("priority") == "high" and r.get("status") == "pending"
    ][:5]


def _get_trend_summary(active_ideas: list[dict]) -> list[str]:
    """Get trend summary lines for active business ideas."""
    trend_lines = []
    trend_emoji = {"up": ":arrow_up:", "down": ":arrow_down:", "flat": ":arrow_right:"}

    for idea in active_ideas:
        bid = idea.get("id", "")
        if not bid:
            continue
        try:
            trend = detect_trends(bid, lookback=7)
        except Exception:
            continue

        if trend.get("days_analyzed", 0) < 2:
            continue

        name = idea.get("name", bid)
        trends = trend.get("trends", {})
        score_trend = trend_emoji.get(trends.get("score", "flat"), ":arrow_right:")
        pv_trend = trend_emoji.get(trends.get("pageviews", "flat"), ":arrow_right:")
        latest = trend.get("latest_score", 0)
        avg = trend.get("avg_score", 0)

        line = f"  *{name}*: スコア {latest} (平均{avg:.0f}) {score_trend} / PV {pv_trend}"
        trend_lines.append(line)

        # Add anomalies
        for anomaly in trend.get("anomalies", []):
            trend_lines.append(f"    :rotating_light: {anomaly}")

    return trend_lines


def _get_recent_insights() -> list[str]:
    """Get recent high-priority AI insights for the report."""
    try:
        rows = get_all_rows("learning_memory")
    except Exception:
        return []

    # Filter active, high priority, recent insights
    active_insights = [
        r for r in rows
        if r.get("status") == "active"
        and r.get("priority") in ("high", "medium")
        and r.get("type") in ("insight", "pattern")
    ]

    # Sort by created_at desc, take top 3
    active_insights.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    lines = []
    for ins in active_insights[:3]:
        source = ":robot_face:" if ins.get("source") == "ai_analysis" else ":bust_in_silhouette:"
        priority = ":red_circle:" if ins.get("priority") == "high" else ":large_orange_circle:"
        content = str(ins.get("content", ""))[:100]
        lines.append(f"  {priority}{source} {content}")

    return lines


def build_report() -> str:
    """Build the daily report text for Slack."""
    dashboard_url = "https://lp-app-pi.vercel.app/dashboard"
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%m/%d")

    active_ideas = get_rows_by_status("business_ideas", "active")
    draft_ideas = get_rows_by_status("business_ideas", "draft")
    analytics = _get_daily_analytics()
    sns_counts = _count_daily_sns_posts()
    form_counts = _count_daily_form_submissions()
    top_suggestions = _get_top_suggestions()

    # Get sheet URLs for linking
    try:
        sheet_urls = get_sheet_urls([
            "business_ideas", "analytics", "sns_posts",
            "form_sales_targets", "improvement_suggestions",
            "market_research", "market_selection", "competitor_analysis",
        ])
    except Exception:
        sheet_urls = {}

    bi_link = f" <{sheet_urls['business_ideas']}|📊シート>" if "business_ideas" in sheet_urls else ""
    analytics_link = f" <{sheet_urls['analytics']}|📊シート>" if "analytics" in sheet_urls else ""

    lines = [
        ":chart_with_upwards_trend: *日次レポート*",
        f"対象日: {yesterday}",
        "",
        f":bulb: *事業案*: {len(active_ideas)}件 active / {len(draft_ideas)}件 draft{bi_link}",
        "",
        f"*--- LP パフォーマンス（前日）---*{analytics_link}",
    ]

    if not analytics:
        lines.append("_データなし（GA4設定を確認してください）_")
    else:
        # Sort by pageviews descending
        sorted_ids = sorted(analytics.keys(), key=lambda x: analytics[x]["pageviews"], reverse=True)
        for bid in sorted_ids:
            m = analytics[bid]
            idea_name = bid
            for idea in active_ideas:
                if idea["id"] == bid:
                    idea_name = idea["name"]
                    break
            lines.append(
                f"  *{idea_name}*: "
                f"PV {m['pageviews']} / Session {m['sessions']} / "
                f"CVR {m['conversions']} / 直帰率 {m['bounce_rate']}%"
            )

    sns_link = f" <{sheet_urls['sns_posts']}|📊>" if "sns_posts" in sheet_urls else ""
    form_link = f" <{sheet_urls['form_sales_targets']}|📊>" if "form_sales_targets" in sheet_urls else ""

    lines.extend([
        "",
        "*--- 前日の活動 ---*",
        f":mega: SNS投稿: {sum(sns_counts.values())}件{sns_link}",
        f":envelope: フォーム営業: {sum(form_counts.values())}件{form_link}",
    ])

    # Trend analysis section
    trend_lines = _get_trend_summary(active_ideas)
    if trend_lines:
        lines.extend(["", "*--- トレンド分析 ---*"])
        lines.extend(trend_lines)

    if top_suggestions:
        lines.extend(["", "*--- 優先改善提案 ---*"])
        for s in top_suggestions:
            lines.append(f"  :warning: [{s.get('business_id', '')}] {s.get('suggestion_text', '')[:100]}")

    # AI learning insights section
    insight_lines = _get_recent_insights()
    if insight_lines:
        lines.extend(["", "*--- AI学習インサイト ---*"])
        lines.extend(insight_lines)

    # Budget reallocation proposal
    try:
        from utils.budget_allocator import generate_reallocation_proposal

        budget = generate_reallocation_proposal(lookback_days=7)
        if budget.get("businesses"):
            lines.extend(["", "*--- 予算配分提案 ---*"])
            lines.append(f"月間予算: \u00A5{budget['total_monthly_budget']:,}")
            for b in budget["businesses"]:
                arrow = ":arrow_up:" if b["change_pct"] > 5 else ":arrow_down:" if b["change_pct"] < -5 else ":arrow_right:"
                proposed_yen = int(budget["total_monthly_budget"] * b["proposed_allocation_pct"] / 100)
                lines.append(
                    f"  {arrow} *{b['name']}*: {b['proposed_allocation_pct']:.0f}% "
                    f"(\u00A5{proposed_yen:,}) — {b['rationale']}"
                )
            if budget.get("summary"):
                lines.append(f"\n:bulb: {budget['summary']}")
    except Exception as e:
        logger.warning(f"Budget allocation failed: {e}")

    # Market exploration links if data exists
    mr_link = f"<{sheet_urls['market_research']}|市場調査>" if "market_research" in sheet_urls else ""
    ms_link = f"<{sheet_urls['market_selection']}|市場選定>" if "market_selection" in sheet_urls else ""
    ca_link = f"<{sheet_urls['competitor_analysis']}|競合分析>" if "competitor_analysis" in sheet_urls else ""
    exploration_links = " / ".join(lnk for lnk in [mr_link, ms_link, ca_link] if lnk)
    if exploration_links:
        lines.append(f"\n📊 *スプレッドシート:* {exploration_links}")

    lines.extend(["", f"<{dashboard_url}|ダッシュボードで詳細を確認>"])

    return "\n".join(lines)


def main():
    logger.info("=== Slack reporter start ===")
    update_status("5_slack_reporter", "running", "日次レポート生成中...")

    try:
        report = build_report()
        slack_notify(report)
        update_status("5_slack_reporter", "success", "レポート送信完了")
        logger.info("=== Slack reporter complete ===")
    except Exception as e:
        update_status("5_slack_reporter", "error", str(e))
        logger.error(f"Slack reporter failed: {e}")
        raise


if __name__ == "__main__":
    main()
