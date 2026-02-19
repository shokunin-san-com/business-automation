"""
Kill judge — automatic business sunset recommendation.

Evaluates active businesses against kill criteria and flags underperformers.
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_logger
from utils.sheets_client import get_all_rows, get_rows_by_status, find_row_index, get_worksheet

logger = get_logger("kill_judge")


def _load_settings() -> dict:
    rows = get_all_rows("settings")
    return {r["key"]: r["value"] for r in rows}


def evaluate_kill_criteria() -> list[dict]:
    """Evaluate all active businesses against kill criteria.

    Returns list of businesses recommended for sunset:
    [
        {
            "business_id": str,
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

    active_ideas = get_rows_by_status("business_ideas", "active")
    if not active_ideas:
        return []

    perf_rows = get_all_rows("performance_log")

    results = []

    for idea in active_ideas:
        bid = idea.get("id", "")
        name = idea.get("name", bid)
        created = idea.get("created_at", "")

        if not bid:
            continue

        # Check if business has been active long enough
        if created and str(created)[:10] > cutoff:
            continue  # Too new, skip

        # Get performance records in evaluation window
        biz_perf = [
            r for r in perf_rows
            if r.get("business_id") == bid and str(r.get("date", "")) >= cutoff
        ]

        if not biz_perf:
            # No performance data at all after eval_days -> warning
            results.append({
                "business_id": bid,
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
            # Determine severity
            recommendation = "kill" if len(reasons) >= 2 else "warning"
            if total_cv == 0 and avg_score < min_score / 2:
                recommendation = "kill"

            results.append({
                "business_id": bid,
                "name": name,
                "reason": " / ".join(reasons),
                "avg_score": round(avg_score, 1),
                "total_cv": total_cv,
                "days_active": len(biz_perf),
                "recommendation": recommendation,
            })

    logger.info(f"Kill judge: {len(results)} businesses flagged out of {len(active_ideas)} active")
    return results


def apply_kill_flag(business_id: str) -> bool:
    """Set a business status to 'sunset_recommended'.

    Does NOT auto-kill. Only flags for human review.
    Returns True if flag was set.
    """
    ws = get_worksheet("business_ideas")
    headers = ws.row_values(1)
    status_col = headers.index("status") + 1 if "status" in headers else None

    if not status_col:
        return False

    row_idx = find_row_index("business_ideas", "id", business_id)
    if not row_idx:
        return False

    current = ws.cell(row_idx, status_col).value
    if current == "active":
        ws.update_cell(row_idx, status_col, "sunset_recommended")
        logger.info(f"Flagged {business_id} as sunset_recommended")
        return True

    return False
