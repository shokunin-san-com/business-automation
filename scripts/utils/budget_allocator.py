"""
Budget allocator — cross-business budget reallocation recommendations.

Compares performance across all active businesses and suggests moving budget
from underperformers to top performers.
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_logger
from utils.sheets_client import get_all_rows
from utils.v2_markets import get_active_v2_markets

logger = get_logger("budget_allocator")


def _load_settings() -> dict:
    rows = get_all_rows("settings")
    return {r["key"]: r["value"] for r in rows}


def generate_reallocation_proposal(lookback_days: int = 7) -> dict:
    """Analyze all active businesses and propose budget reallocation.

    Returns:
        {
            "total_monthly_budget": int,
            "businesses": [
                {
                    "id": str,
                    "name": str,
                    "current_allocation_pct": float,
                    "proposed_allocation_pct": float,
                    "change_pct": float,
                    "rationale": str,
                    "rank": int,
                    "metrics": {
                        "avg_score": float,
                        "total_cv": int,
                        "total_pv": int,
                        "efficiency": float,
                    }
                }
            ],
            "summary": str,
        }
    """
    settings = _load_settings()
    total_budget = int(settings.get("monthly_ad_budget", "100000"))

    cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    # V2: Read active markets from lp_ready_log + gate_decision_log
    active_ideas = get_active_v2_markets()
    if not active_ideas:
        return {"total_monthly_budget": total_budget, "businesses": [], "summary": "active事業なし"}

    perf_rows = get_all_rows("performance_log")

    # Aggregate metrics per business
    biz_metrics = {}
    for idea in active_ideas:
        bid = idea.get("id", "")
        name = idea.get("name", bid)

        biz_perf = [
            r for r in perf_rows
            if r.get("business_id") == bid and str(r.get("date", "")) >= cutoff
        ]

        total_pv = sum(int(r.get("lp_pageviews", 0)) for r in biz_perf)
        total_cv = sum(int(r.get("lp_conversions", 0)) for r in biz_perf)
        scores = [int(r.get("performance_score", 0)) for r in biz_perf]
        avg_score = sum(scores) / len(scores) if scores else 0
        efficiency = total_cv / max(total_pv, 1)

        biz_metrics[bid] = {
            "id": bid,
            "name": name,
            "avg_score": round(avg_score, 1),
            "total_cv": total_cv,
            "total_pv": total_pv,
            "efficiency": round(efficiency, 4),
            "data_days": len(biz_perf),
        }

    if not biz_metrics:
        return {"total_monthly_budget": total_budget, "businesses": [], "summary": "データ不足"}

    # Rank by composite score: 50% avg_score + 30% efficiency + 20% total_cv
    def composite(m):
        return (m["avg_score"] / 100) * 0.5 + min(m["efficiency"] * 100, 1) * 0.3 + min(m["total_cv"] / 10, 1) * 0.2

    ranked = sorted(biz_metrics.values(), key=composite, reverse=True)

    # Allocation strategy
    n = len(ranked)
    if n == 1:
        allocations = [100.0]
    elif n == 2:
        allocations = [65.0, 35.0]
    elif n == 3:
        allocations = [50.0, 35.0, 15.0]
    else:
        top_pct = 40.0
        mid_count = max(n // 3, 1)
        bot_count = n - 1 - mid_count
        mid_each = 35.0 / max(mid_count, 1)
        bot_each = 25.0 / max(bot_count, 1)

        allocations = [top_pct]
        allocations.extend([mid_each] * mid_count)
        allocations.extend([bot_each] * bot_count)
        allocations = allocations[:n]

    # Equal baseline for comparison
    equal_pct = 100.0 / n

    businesses = []
    for i, biz in enumerate(ranked):
        proposed = allocations[i] if i < len(allocations) else 0
        change = proposed - equal_pct

        if change > 10:
            rationale = f"トップパフォーマー — 予算増額推奨（スコア{biz['avg_score']}, CV{biz['total_cv']}件）"
        elif change < -10:
            rationale = f"パフォーマンス低迷 — 予算削減検討（スコア{biz['avg_score']}, CV{biz['total_cv']}件）"
        else:
            rationale = f"現状維持（スコア{biz['avg_score']}, CV{biz['total_cv']}件）"

        businesses.append({
            "id": biz["id"],
            "name": biz["name"],
            "current_allocation_pct": round(equal_pct, 1),
            "proposed_allocation_pct": round(proposed, 1),
            "change_pct": round(change, 1),
            "rationale": rationale,
            "rank": i + 1,
            "metrics": {
                "avg_score": biz["avg_score"],
                "total_cv": biz["total_cv"],
                "total_pv": biz["total_pv"],
                "efficiency": biz["efficiency"],
            },
        })

    # Summary
    top = businesses[0] if businesses else None
    summary = ""
    if top:
        summary = (
            f"推奨: 「{top['name']}」に予算{top['proposed_allocation_pct']:.0f}%集中"
            f"（スコア{top['metrics']['avg_score']}, CV{top['metrics']['total_cv']}件）"
        )
        if len(businesses) > 1:
            bottom = businesses[-1]
            summary += f" / 「{bottom['name']}」は{bottom['proposed_allocation_pct']:.0f}%に縮小"

    return {
        "total_monthly_budget": total_budget,
        "businesses": businesses,
        "summary": summary,
    }
