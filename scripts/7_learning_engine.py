"""
7_learning_engine.py — Daily AI learning job.

Aggregates performance data, detects trends, generates insights,
and maintains the learning memory for continuous AI improvement.

Scheduled to run daily at 2:00 AM JST (after analytics_reporter).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_logger
from utils.learning_engine import (
    aggregate_daily_performance,
    detect_trends,
    generate_insights,
    expire_old_insights,
)
from utils.sheets_client import get_rows_by_status
from utils.slack_notifier import send_message as slack_notify
from utils.status_writer import update_status

logger = get_logger("learning_engine_job", "learning_engine.log")


def main():
    logger.info("=== Learning engine start ===")
    update_status("7_learning_engine", "running", "パフォーマンスデータ集計中...")

    try:
        # 1. Aggregate daily performance
        performance = aggregate_daily_performance()
        logger.info(f"Aggregated performance for {len(performance)} businesses")

        # 2. Detect trends for active ideas
        update_status("7_learning_engine", "running", "トレンド分析中...")
        active_ideas = get_rows_by_status("business_ideas", "active")
        trends = []
        for idea in active_ideas:
            bid = idea.get("id", "")
            if bid:
                trend = detect_trends(bid, lookback=14)
                if trend.get("days_analyzed", 0) >= 2:
                    trends.append(trend)
        logger.info(f"Detected trends for {len(trends)} businesses")

        # 3. Generate AI insights
        update_status("7_learning_engine", "running", "AIインサイト生成中...")
        insights = []
        if performance or trends:
            insights = generate_insights(performance, trends)
            logger.info(f"Generated {len(insights)} insights")

        # 4. Expire old insights
        expired_count = expire_old_insights(max_age_days=30)

        # 5. Notify
        total_insights = len(insights)
        if total_insights > 0:
            high_priority = [i for i in insights if i.get("priority") == "high"]
            msg = (
                f":brain: 学習エンジン完了: "
                f"*{len(performance)}件* のパフォーマンス集計、"
                f"*{total_insights}件* のインサイト生成"
            )
            if high_priority:
                msg += f"\n:warning: 高優先: {len(high_priority)}件"
                for hp in high_priority[:3]:
                    msg += f"\n> {hp.get('content', '')[:80]}"
            if expired_count:
                msg += f"\n:wastebasket: {expired_count}件の古いインサイト失効"
            slack_notify(msg)

        update_status("7_learning_engine", "success", f"{total_insights}件インサイト", {
            "performance_records": len(performance),
            "trends_analyzed": len(trends),
            "insights_generated": total_insights,
            "expired": expired_count,
        })
        logger.info(f"=== Learning engine complete: {total_insights} insights ===")

    except Exception as e:
        update_status("7_learning_engine", "error", str(e))
        logger.error(f"Learning engine failed: {e}")
        raise


if __name__ == "__main__":
    main()
