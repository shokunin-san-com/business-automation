"""
Kill judge — V2: automatic market sunset recommendation.

Evaluates READY markets against kill criteria using V2 data sources.
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_logger
from utils.sheets_client import get_all_rows
from utils.v2_markets import get_active_v2_markets

logger = get_logger("kill_judge")


def _load_settings() -> dict:
    rows = get_all_rows("settings")
    return {r["key"]: r["value"] for r in rows}


def evaluate_kill_criteria() -> list[dict]:
    """Evaluate active V2 markets against kill criteria.

    Returns list of markets recommended for sunset:
    [
        {
            "run_id": str,
            "name": str,
            "reason": str,
            "avg_score": float,
            "total_cv": int,
            "days_active": int,
            "recommendation": "kill" | "warning"
        }
    ]
    """
    settings = _load_settings()

    if settings.get("kill_criteria_enabled", "true").lower() != "true":
        logger.info("Kill criteria disabled, skipping")
        return []

    eval_days = int(settings.get("kill_criteria_days", "14"))
    min_cv = int(settings.get("kill_criteria_min_cv", "1"))
    min_score = float(settings.get("kill_criteria_min_score", "15"))

    cutoff = (datetime.now() - timedelta(days=eval_days)).strftime("%Y-%m-%d")

    # V2: Read active markets from lp_ready_log + gate_decision_log
    active_markets = get_active_v2_markets()
    if not active_markets:
        return []

    perf_rows = get_all_rows("performance_log")

    results = []

    for market in active_markets:
        rid = market.get("id", "")
        name = market.get("name", rid[:8])

        if not rid:
            continue

        # Get performance records in evaluation window
        biz_perf = [
            r for r in perf_rows
            if r.get("business_id") == rid and str(r.get("date", "")) >= cutoff
        ]

        if not biz_perf:
            results.append({
                "run_id": rid,
                "name": name,
                "reason": f"{eval_days}日間パフォーマンスデータなし",
                "avg_score": 0,
                "total_cv": 0,
                "days_active": 0,
                "recommendation": "warning",
            })
            continue

        # Calculate metrics
        total_cv = sum(int(r.get("lp_conversions", 0)) for r in biz_perf)
        avg_score = sum(int(r.get("performance_score", 0)) for r in biz_perf) / len(biz_perf)
        total_pv = sum(int(r.get("lp_pageviews", 0)) for r in biz_perf)

        reasons = []

        if total_cv < min_cv:
            reasons.append(f"CV {total_cv}件（基準: {min_cv}件以上）")

        if avg_score < min_score:
            reasons.append(f"平均スコア {avg_score:.1f}（基準: {min_score}以上）")

        if total_pv == 0 and len(biz_perf) >= 7:
            reasons.append("PV完全ゼロ")

        if reasons:
            recommendation = "kill" if len(reasons) >= 2 else "warning"
            if total_cv == 0 and avg_score < min_score / 2:
                recommendation = "kill"

            results.append({
                "run_id": rid,
                "name": name,
                "reason": " / ".join(reasons),
                "avg_score": round(avg_score, 1),
                "total_cv": total_cv,
                "days_active": len(biz_perf),
                "recommendation": recommendation,
            })

    logger.info(f"Kill judge: {len(results)} markets flagged out of {len(active_markets)} active")
    return results
