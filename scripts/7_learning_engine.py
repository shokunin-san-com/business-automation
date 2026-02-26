"""
7_learning_engine.py — Daily AI learning job.

Aggregates performance data, detects trends, generates insights,
and maintains the learning memory for continuous AI improvement.

Scheduled to run daily at 19:00 JST.
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
    aggregate_v2_pipeline_metrics,
    detect_v2_trends,
    generate_v2_insights,
)
from utils.downstream_metrics import aggregate_daily_downstream, get_latest_downstream_kpis
from utils.claude_client import generate_json
from utils.sheets_client import get_rows_by_status, get_all_rows
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

        # 2. Detect trends for active offers (V2: offer_3_log replaces business_ideas)
        update_status("7_learning_engine", "running", "トレンド分析中...")
        trends = []
        try:
            active_offers = get_all_rows("offer_3_log")
            # Use unique run_ids as "business" identifiers for trend tracking
            seen_runs = set()
            for offer in active_offers:
                rid = offer.get("run_id", "")
                if rid and rid not in seen_runs:
                    seen_runs.add(rid)
                    trend = detect_trends(rid, lookback=14)
                    if trend.get("days_analyzed", 0) >= 2:
                        trends.append(trend)
        except Exception as te:
            logger.warning(f"Trend detection skipped (non-fatal): {te}")
        logger.info(f"Detected trends for {len(trends)} offers")

        # 3. Generate AI insights
        update_status("7_learning_engine", "running", "AIインサイト生成中...")
        insights = []
        if performance or trends:
            insights = generate_insights(performance, trends)
            logger.info(f"Generated {len(insights)} insights")

        # 4. Expire old insights
        expired_count = expire_old_insights(max_age_days=30)

        # 5. Kill criteria evaluation (V2: skipped — business_ideas廃止済み)
        # V1のbusiness_ideasシートは削除済み。V2ではgate_decision_logのPASS/FAILで管理。
        kill_results = []
        kill_flagged = 0

        # 6. V2 pipeline learning
        v2_insights = []
        try:
            update_status("7_learning_engine", "running", "V2パイプライン学習中...")
            v2_metrics = aggregate_v2_pipeline_metrics()
            v2_trends = detect_v2_trends()
            if v2_metrics.get("runs_analyzed", 0) > 0:
                v2_insights = generate_v2_insights(v2_metrics, v2_trends)
                logger.info(f"Generated {len(v2_insights)} V2 insights")
        except Exception as v2e:
            logger.warning(f"V2 learning failed (non-fatal): {v2e}")

        # 7. Downstream KPI integration
        downstream_kpi = {}
        try:
            update_status("7_learning_engine", "running", "下流KPI統合中...")
            downstream_kpi = aggregate_daily_downstream()
            logger.info(f"Downstream KPI: inquiries={downstream_kpi.get('total_inquiries', 0)}, "
                        f"deal_rate={downstream_kpi.get('deal_rate', 0)}")
        except Exception as de:
            logger.warning(f"Downstream KPI aggregation failed (non-fatal): {de}")

        # 8. Expansion data learning
        expansion_insights = 0
        try:
            update_status("7_learning_engine", "running", "拡張データ学習中...")
            winning_patterns = get_all_rows("winning_patterns")
            active_patterns = [p for p in winning_patterns if p.get("status") not in ("archived", "saturated")]
            if active_patterns:
                # Learn from winning pattern characteristics
                pattern_summary = "\n".join([
                    f"- {p.get('micro_market', '?')}: {p.get('pattern_type', '?')}, status={p.get('status', '?')}"
                    for p in active_patterns[:10]
                ])
                expansion_prompt = f"""以下の勝ちパターンデータから、V2パイプラインの探索・オファー生成に活かせるインサイトを生成してください。

## 勝ちパターン ({len(active_patterns)}件)
{pattern_summary}

JSON配列で回答:
[{{"content": "インサイト", "category": "expansion_strategy", "priority": "high"|"medium"|"low", "confidence": 0.0-1.0, "type": "pattern"}}]

2-3件で簡潔に。"""
                try:
                    exp_insights = generate_json(
                        prompt=expansion_prompt,
                        system="あなたは事業拡張戦略の専門家です。勝ちパターンから次の探索に活かせる教訓を抽出してください。",
                        max_tokens=1024,
                        temperature=0.5,
                    )
                    if isinstance(exp_insights, dict):
                        exp_insights = exp_insights.get("insights", [exp_insights])
                    if isinstance(exp_insights, list):
                        from utils.learning_engine import _save_insights
                        saved = _save_insights(exp_insights)
                        expansion_insights = len(saved)
                        logger.info(f"Generated {expansion_insights} expansion strategy insights")
                except Exception as ei:
                    logger.warning(f"Expansion insight generation failed: {ei}")
        except Exception as ee:
            logger.warning(f"Expansion data learning failed (non-fatal): {ee}")

        # 9. Notify kills
        if kill_results:
            kill_msg_parts = [":skull: *損切り判定レポート*\n"]
            for kr in kill_results:
                emoji = ":red_circle:" if kr["recommendation"] == "kill" else ":warning:"
                action = "撤退推奨" if kr["recommendation"] == "kill" else "要注意"
                kill_msg_parts.append(
                    f"{emoji} *{kr['name']}* — {action}\n"
                    f"  理由: {kr['reason']}\n"
                    f"  平均スコア: {kr['avg_score']} / CV: {kr['total_cv']}件 / データ日数: {kr['days_active']}日"
                )
            slack_notify("\n".join(kill_msg_parts))

        # 10. Notify insights
        total_insights = len(insights) + len(v2_insights) + expansion_insights
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
            if kill_flagged:
                msg += f"\n:skull: {kill_flagged}件の事業に撤退推奨フラグ"
            slack_notify(msg)

        update_status("7_learning_engine", "success", f"{total_insights}件インサイト / {kill_flagged}件撤退推奨", {
            "performance_records": len(performance),
            "trends_analyzed": len(trends),
            "insights_generated": total_insights,
            "v2_insights": len(v2_insights),
            "expired": expired_count,
            "kill_flagged": kill_flagged,
            "downstream_inquiries": downstream_kpi.get("total_inquiries", 0),
            "downstream_deal_rate": downstream_kpi.get("deal_rate", 0),
        })
        logger.info(f"=== Learning engine complete: {total_insights} insights ===")

    except Exception as e:
        update_status("7_learning_engine", "error", str(e))
        logger.error(f"Learning engine failed: {e}")
        raise


if __name__ == "__main__":
    main()
