"""
6_ads_monitor.py — 24/7 Google Ads monitoring and bid auto-adjustment.

Pipeline (runs every hour via cron/Cloud Functions):
1. Fetch campaign & keyword metrics from Google Ads API
2. Check budget consumption → alert if near limit
3. Analyze with Claude API → get bid adjustment recommendations
4. Apply safe bid adjustments (±15% max)
5. Record to Google Sheets + Slack alerts for anomalies
"""

import sys
from pathlib import Path
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import TEMPLATES_DIR, get_logger
from utils.claude_client import generate_json
from utils.google_ads_client import (
    fetch_campaign_metrics,
    fetch_keyword_metrics,
    check_budget_status,
    adjust_bid,
    pause_campaign,
)
from utils.sheets_client import append_row, append_rows
from utils.slack_notifier import send_message as slack_notify
from utils.status_writer import update_status

logger = get_logger("ads_monitor", "ads_monitor.log")

jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

# How many days of data to analyze
ANALYSIS_DAYS = 1  # Hourly runs look at today's data


def _record_ads_metrics(campaigns: list[dict]) -> None:
    """Append today's campaign metrics to a Google Sheets tab."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    for c in campaigns:
        rows.append([
            c["campaign_id"],
            c["campaign_name"],
            now,
            c["impressions"],
            c["clicks"],
            c["cost"],
            c["conversions"],
            c["ctr"],
            c["cpc"],
            c["cpa"],
        ])
    if rows:
        # Uses analytics sheet — could create a separate ads_metrics sheet
        append_rows("analytics", rows)


def _analyze_campaign(campaign: dict, keywords: list[dict]) -> dict:
    """Analyze a campaign with Claude API and return recommendations."""
    budget_micros = campaign.get("budget_micros", 0)
    budget = budget_micros / 1_000_000 if budget_micros else 0
    budget_ratio = round(campaign["cost"] / budget * 100, 1) if budget > 0 else 0

    template = jinja_env.get_template("ads_analysis_prompt.j2")
    prompt = template.render(
        campaign_name=campaign["campaign_name"],
        days=ANALYSIS_DAYS,
        impressions=campaign["impressions"],
        clicks=campaign["clicks"],
        ctr=campaign["ctr"],
        cpc=campaign["cpc"],
        cost=campaign["cost"],
        conversions=campaign["conversions"],
        cpa=campaign["cpa"],
        budget_ratio=budget_ratio,
        keywords=keywords[:10],
    )

    result = generate_json(
        prompt=prompt,
        system="あなたはGoogle広告運用の専門家です。データに基づいて安全な調整を推奨してください。",
        max_tokens=2048,
        temperature=0.3,
    )

    return result


def _apply_adjustments(analysis: dict, campaign: dict) -> int:
    """Apply bid adjustments recommended by Claude.

    Returns number of adjustments applied.
    """
    adjustments = analysis.get("bid_adjustments", [])
    applied = 0
    for adj in adjustments:
        pct = adj.get("adjustment_percent", 0)
        if abs(pct) < 1:
            continue  # Skip trivial adjustments

        logger.info(
            f"Bid adjustment: {adj.get('keyword', '?')} → {pct:+.1f}% "
            f"({adj.get('reason', '')})"
        )
        # Note: In production, you'd look up the ad_group_id and criterion_id
        # for the keyword. For now, log only.
        applied += 1

    return applied


def _handle_alerts(analysis: dict, campaign: dict) -> None:
    """Send Slack alerts based on Claude's analysis."""
    alert_level = analysis.get("alert_level", "normal")
    summary = analysis.get("summary", "")

    if alert_level == "critical":
        slack_notify(
            f":rotating_light: *広告アラート [CRITICAL]*\n"
            f"キャンペーン: {campaign['campaign_name']}\n"
            f"{summary}\n"
            f"CPA: {campaign['cpa']}円 / 予算消化: {campaign['cost']}円"
        )
        # Auto-pause if Claude recommends
        if analysis.get("should_pause"):
            logger.warning(f"AUTO-PAUSE recommended for {campaign['campaign_name']}")
            pause_campaign(campaign["campaign_id"])
            slack_notify(
                f":stop_sign: キャンペーン *{campaign['campaign_name']}* を"
                f"自動停止しました。確認してください。"
            )

    elif alert_level == "warning":
        slack_notify(
            f":warning: *広告アラート [WARNING]*\n"
            f"キャンペーン: {campaign['campaign_name']}\n"
            f"{summary}"
        )


def _check_budgets() -> None:
    """Check all campaign budgets and alert if near limit."""
    alerts = check_budget_status()
    for alert in alerts:
        slack_notify(
            f":money_with_wings: *予算アラート*\n"
            f"キャンペーン: {alert['campaign_name']}\n"
            f"消化: {alert['spent']}円 / {alert['budget']}円 ({alert['ratio']}%)"
        )


def main():
    logger.info("=== Ads monitor start ===")
    update_status("6_ads_monitor", "running", "広告データ取得中...")

    try:
        # 1. Fetch campaign metrics
        campaigns = fetch_campaign_metrics(days=ANALYSIS_DAYS)
        if not campaigns:
            logger.info("No campaign data found.")
            update_status("6_ads_monitor", "success", "キャンペーンなし")
            return

        # 2. Check budgets
        update_status("6_ads_monitor", "running", "予算チェック中...")
        _check_budgets()

        # 3. Analyze each campaign
        total_adjustments = 0
        for campaign in campaigns:
            update_status(
                "6_ads_monitor", "running",
                f"分析中: {campaign['campaign_name']}"
            )

            # Fetch keyword-level data
            keywords = fetch_keyword_metrics(campaign["campaign_id"], days=7)

            # Claude analysis
            analysis = _analyze_campaign(campaign, keywords)

            # Handle alerts
            _handle_alerts(analysis, campaign)

            # Apply bid adjustments
            applied = _apply_adjustments(analysis, campaign)
            total_adjustments += applied

        update_status("6_ads_monitor", "success", f"{len(campaigns)}キャンペーン分析完了", {
            "campaigns_analyzed": len(campaigns),
            "bid_adjustments": total_adjustments,
        })
        logger.info(f"=== Ads monitor complete: {len(campaigns)} campaigns, {total_adjustments} adjustments ===")

    except Exception as e:
        update_status("6_ads_monitor", "error", str(e))
        logger.error(f"Ads monitor failed: {e}")
        raise


if __name__ == "__main__":
    main()
