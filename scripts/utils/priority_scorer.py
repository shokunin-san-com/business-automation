"""
priority_scorer.py — Real-data priority scoring for market selection.

Uses actual data signals (not AI scoring) to prioritize markets:
  1. Search volume indicators (from search_volume_log)
  2. Competitor gap count (from competitor_20_log)
  3. Ad presence (real advertiser activity = money in market)
  4. Related keyword density

Output: priority_score_log with ranked markets.
No AI scoring — all metrics are from real data.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_logger
from utils.sheets_client import get_all_rows, append_rows, ensure_sheet_exists

logger = get_logger("priority_scorer", "priority_scorer.log")

PRIORITY_SHEET = "priority_score_log"
PRIORITY_HEADERS = [
    "run_id", "micro_market", "search_result_avg", "ads_keyword_count",
    "competitor_count", "gap_count", "related_kw_count",
    "priority_rank", "priority_tier", "scored_at",
]

# Tier thresholds (based on real signals, not AI scores)
TIER_A_MIN_ADS = 2       # At least 2 keywords have ads
TIER_A_MIN_RESULTS = 50000
TIER_B_MIN_ADS = 1
TIER_B_MIN_RESULTS = 10000


def _get_search_volume_data(run_id: str) -> dict[str, dict]:
    """Load search volume data for a run, grouped by micro_market."""
    try:
        rows = get_all_rows("search_volume_log")
    except Exception:
        return {}

    by_market: dict[str, dict] = {}
    for r in rows:
        if r.get("run_id") != run_id:
            continue
        market = r.get("micro_market", "")
        if market not in by_market:
            by_market[market] = {
                "total_results": 0,
                "keyword_count": 0,
                "ads_count": 0,
                "related_kws": set(),
            }
        m = by_market[market]
        m["total_results"] += int(r.get("result_count", 0) or 0)
        m["keyword_count"] += 1
        if str(r.get("has_ads", "")).lower() == "true":
            m["ads_count"] += 1
        try:
            related = json.loads(r.get("related_keywords", "[]"))
            if isinstance(related, list):
                m["related_kws"].update(related)
        except Exception:
            pass

    return by_market


def _get_competitor_data(run_id: str) -> dict[str, dict]:
    """Load competitor analysis data for a run."""
    try:
        rows = get_all_rows("competitor_20_log")
    except Exception:
        return {}

    by_market: dict[str, dict] = {}
    for r in rows:
        if r.get("run_id") != run_id:
            continue
        market = r.get("market_name", "")
        if market not in by_market:
            by_market[market] = {"count": 0}
        by_market[market]["count"] += 1

    return by_market


def score_markets(
    run_id: str,
    passed_markets: list[dict],
) -> list[dict]:
    """Score and rank markets based on real data signals.

    Returns list of scored markets sorted by priority (best first).
    """
    ensure_sheet_exists(PRIORITY_SHEET, PRIORITY_HEADERS)

    sv_data = _get_search_volume_data(run_id)
    comp_data = _get_competitor_data(run_id)

    scored = []
    for market in passed_markets:
        name = market.get("micro_market", "")

        sv = sv_data.get(name, {})
        kw_count = sv.get("keyword_count", 1) or 1
        avg_results = sv.get("total_results", 0) / kw_count
        ads_count = sv.get("ads_count", 0)
        related_count = len(sv.get("related_kws", set()))

        comp = comp_data.get(name, {})
        comp_count = comp.get("count", 0)

        # Gap count from competitor analysis (stored separately in gap_top3)
        gap_count = market.get("gap_count", 0)

        # Determine tier
        if ads_count >= TIER_A_MIN_ADS and avg_results >= TIER_A_MIN_RESULTS:
            tier = "A"
        elif ads_count >= TIER_B_MIN_ADS or avg_results >= TIER_B_MIN_RESULTS:
            tier = "B"
        else:
            tier = "C"

        # Composite rank score (higher = better)
        # Weighted by: ads presence (strongest signal) > search volume > competitors > related KWs
        rank_score = (
            ads_count * 1000
            + min(avg_results / 100, 500)
            + comp_count * 10
            + related_count * 5
            + gap_count * 50
        )

        scored.append({
            "micro_market": name,
            "search_result_avg": int(avg_results),
            "ads_keyword_count": ads_count,
            "competitor_count": comp_count,
            "gap_count": gap_count,
            "related_kw_count": related_count,
            "priority_tier": tier,
            "rank_score": rank_score,
            **market,
        })

    # Sort by rank_score descending
    scored.sort(key=lambda x: x["rank_score"], reverse=True)

    # Assign rank
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows_to_save = []
    for i, s in enumerate(scored, 1):
        s["priority_rank"] = i
        rows_to_save.append([
            run_id,
            s["micro_market"],
            s["search_result_avg"],
            s["ads_keyword_count"],
            s["competitor_count"],
            s["gap_count"],
            s["related_kw_count"],
            i,
            s["priority_tier"],
            now,
        ])

    if rows_to_save:
        append_rows(PRIORITY_SHEET, rows_to_save)
        logger.info(f"Saved {len(rows_to_save)} priority scores")

    return scored
