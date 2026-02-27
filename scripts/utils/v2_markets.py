"""
V2 market data loader — shared utility for all downstream scripts.

Replaces V1 `get_rows_by_status("business_ideas", "active")` pattern.
Reads from V2 sheets: lp_ready_log, gate_decision_log, offer_3_log.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_logger
from utils.sheets_client import get_all_rows

logger = get_logger("v2_markets")


def get_active_v2_markets() -> list[dict]:
    """Get active markets from V2 pipeline sheets.

    Joins: lp_ready_log (READY) + gate_decision_log (PASS) + offer_3_log.

    Returns list of dicts with both V2 fields and V1-compatible fields:
        id: run_id
        name: micro_market name
        payer: who pays
        offers: list of offer dicts (max 3)
        # V1-compatible fields (for templates that still use old field names)
        description: constructed from offers/blackout_hypothesis
        target_audience: payer
        category: micro_market
        differentiator: first offer's deliverable
        market_size: ""  (not available in V2)
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
    gate_by_run: dict[str, dict] = {}
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
        if not gate:
            continue  # No PASS gate → skip

        offers = offers_by_run.get(rid, [])[:3]
        market_name = gate.get("micro_market", rid[:8])
        payer = gate.get("payer", "")
        if not payer and offers:
            payer = offers[0].get("payer", "")

        # Build description from offers
        offer_desc_parts = []
        for o in offers:
            offer_desc_parts.append(
                f"{o.get('offer_name', '')}: {o.get('deliverable', '')}"
            )
        description = " / ".join(offer_desc_parts) if offer_desc_parts else gate.get("blackout_hypothesis", "")

        markets.append({
            # V2 fields
            "id": rid,
            "name": market_name,
            "payer": payer,
            "offers": offers,
            "evidence_urls": gate.get("evidence_urls", ""),
            "blackout_hypothesis": gate.get("blackout_hypothesis", ""),
            # V1-compatible fields
            "description": description,
            "target_audience": payer,
            "category": market_name,
            "differentiator": offers[0].get("deliverable", "") if offers else "",
            "market_size": "",
        })

    logger.info(f"Found {len(markets)} active V2 markets")
    return markets
