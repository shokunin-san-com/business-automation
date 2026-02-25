"""
Expansion engine — detect winning patterns, generate SOPs, recommend budgets.

Phase 3 of CEO strategy: scale what works.
"""
from __future__ import annotations

import json
import uuid
import logging
from datetime import datetime, timedelta

from utils.claude_client import generate_json
from utils.sheets_client import (
    get_all_rows,
    append_rows,
    get_setting,
)

logger = logging.getLogger(__name__)


def detect_winning_patterns(
    min_inquiries: int | None = None,
    min_deal_rate: float | None = None,
    min_days: int | None = None,
) -> list[dict]:
    """Scan all active businesses and identify winning patterns.

    Criteria (configurable via settings):
    - min_inquiries: Minimum total inquiries
    - min_deal_rate: Minimum deal close rate
    - min_days: Minimum days of operation

    Returns:
        List of candidate winning pattern dicts.
    """
    # Load thresholds from settings or use defaults
    if min_inquiries is None:
        min_inquiries = int(get_setting("expansion_min_inquiries", "5"))
    if min_deal_rate is None:
        min_deal_rate = float(get_setting("expansion_min_deal_rate", "0.1"))
    if min_days is None:
        min_days = int(get_setting("expansion_min_days", "14"))

    inquiries = get_all_rows("inquiry_log")
    deals = get_all_rows("deal_pipeline")
    gates = get_all_rows("gate_decision_log")
    offers = get_all_rows("offer_3_log")
    lp_ready = get_all_rows("lp_ready_log")

    # Group inquiries by business_id
    inq_by_biz: dict[str, list] = {}
    for r in inquiries:
        bid = r.get("business_id", "")
        if bid:
            inq_by_biz.setdefault(bid, []).append(r)

    # Group deals by business_id
    deals_by_biz: dict[str, list] = {}
    for r in deals:
        bid = r.get("business_id", "")
        if bid:
            deals_by_biz.setdefault(bid, []).append(r)

    candidates = []

    for bid, biz_inquiries in inq_by_biz.items():
        total_inq = len(biz_inquiries)
        if total_inq < min_inquiries:
            continue

        biz_deals = deals_by_biz.get(bid, [])
        won = [d for d in biz_deals if d.get("stage") == "won"]
        lost = [d for d in biz_deals if d.get("stage") == "lost"]
        total_closed = len(won) + len(lost)
        deal_rate = len(won) / max(total_closed, 1) if total_closed > 0 else 0

        if deal_rate < min_deal_rate:
            continue

        # Check operation duration
        timestamps = [r.get("timestamp", "") for r in biz_inquiries if r.get("timestamp")]
        if timestamps:
            first = min(timestamps)
            days_active = (datetime.now() - datetime.fromisoformat(first.replace("Z", "+00:00").split("+")[0])).days
        else:
            days_active = 0

        if days_active < min_days:
            continue

        # Get V2 context for this business
        run_ids = set(r.get("run_id", "") for r in biz_inquiries if r.get("run_id"))
        biz_gates = [g for g in gates if g.get("run_id") in run_ids]
        biz_offers = [o for o in offers if o.get("run_id") in run_ids]

        micro_market = biz_gates[0].get("micro_market", "") if biz_gates else ""
        offer_name = biz_offers[0].get("offer_name", "") if biz_offers else ""
        payer = biz_offers[0].get("payer", "") if biz_offers else ""
        lp_url = ""
        biz_lp = [l for l in lp_ready if l.get("run_id") in run_ids and l.get("status") == "READY"]
        if biz_lp:
            lp_url = f"/lp/{bid}"

        # Classify pattern type
        total_deal_value = sum(float(d.get("deal_value", 0) or 0) for d in won)
        if deal_rate >= 0.3 and days_active <= 30:
            pattern_type = "quick_win"
        elif deal_rate >= 0.15 and days_active >= 30:
            pattern_type = "steady_growth"
        else:
            pattern_type = "high_potential"

        candidates.append({
            "business_id": bid,
            "micro_market": micro_market,
            "offer_name": offer_name,
            "payer": payer,
            "lp_url": lp_url,
            "total_inquiries": total_inq,
            "deals_won": len(won),
            "deal_rate": round(deal_rate, 3),
            "total_deal_value": total_deal_value,
            "days_active": days_active,
            "pattern_type": pattern_type,
        })

    logger.info(f"Detected {len(candidates)} winning pattern candidates")
    return candidates


def generate_sop(pattern_data: dict) -> dict:
    """Generate a Standard Operating Procedure for scaling a winning pattern.

    Returns:
        SOP dict with steps, success factors, risks, channels.
    """
    prompt = f"""以下の勝ちパターンの再現・拡張SOPを生成してください。

## 勝ちパターン情報
- 市場: {pattern_data.get('micro_market', '不明')}
- オファー: {pattern_data.get('offer_name', '不明')}
- 支払者: {pattern_data.get('payer', '不明')}
- 問い合わせ数: {pattern_data.get('total_inquiries', 0)}
- 成約数: {pattern_data.get('deals_won', 0)}
- 成約率: {pattern_data.get('deal_rate', 0):.1%}
- 成約金額合計: {pattern_data.get('total_deal_value', 0):,.0f}円
- 運用日数: {pattern_data.get('days_active', 0)}日
- パターン分類: {pattern_data.get('pattern_type', '不明')}

以下のJSON形式で回答:
{{
  "steps": ["step1", "step2", ...],
  "success_factors": ["factor1", "factor2", ...],
  "risks": ["risk1", "risk2", ...],
  "recommended_channels": ["channel1", "channel2", ...],
  "estimated_roi_multiplier": 2.0
}}"""

    try:
        sop = generate_json(
            prompt=prompt,
            system="あなたは事業スケーリングの専門家です。勝ちパターンを効率的に再現・拡張するSOP（標準作業手順書）を設計してください。",
            max_tokens=2048,
            temperature=0.5,
        )
        if isinstance(sop, list) and sop:
            sop = sop[0]
        return sop if isinstance(sop, dict) else {}
    except Exception as e:
        logger.error(f"SOP generation failed: {e}")
        return {}


def generate_budget_recommendation(pattern_data: dict) -> dict:
    """Generate budget allocation recommendations for scaling.

    Returns:
        Budget recommendation dict.
    """
    prompt = f"""以下の勝ちパターンの予算配分を推奨してください。

## パターン情報
- 市場: {pattern_data.get('micro_market', '不明')}
- 成約率: {pattern_data.get('deal_rate', 0):.1%}
- 成約金額合計: {pattern_data.get('total_deal_value', 0):,.0f}円
- 運用日数: {pattern_data.get('days_active', 0)}日
- パターン分類: {pattern_data.get('pattern_type', '不明')}

以下のJSON形式で回答:
{{
  "scaling_recommendation": "maintain" | "2x" | "5x" | "new_channel_test",
  "monthly_budget_recommendation": 50000,
  "allocation": {{
    "lp_improvement": 20,
    "sns_advertising": 30,
    "form_sales_expansion": 20,
    "new_channel_test": 30
  }},
  "rationale": "推奨理由",
  "expected_monthly_deals": 5,
  "confidence": 0.7
}}"""

    try:
        rec = generate_json(
            prompt=prompt,
            system="あなたは事業投資の専門家です。データに基づく予算配分の推奨を行ってください。",
            max_tokens=1024,
            temperature=0.4,
        )
        if isinstance(rec, list) and rec:
            rec = rec[0]
        return rec if isinstance(rec, dict) else {}
    except Exception as e:
        logger.error(f"Budget recommendation failed: {e}")
        return {}


def save_winning_pattern(
    pattern: dict,
    sop: dict,
    budget_rec: dict,
    run_id: str = "",
) -> str:
    """Save a winning pattern to the winning_patterns sheet.

    Returns:
        The pattern_id.
    """
    pattern_id = f"wp_{uuid.uuid4().hex[:8]}"
    now = datetime.now().strftime("%Y-%m-%d")

    row = [
        pattern_id,
        run_id,
        pattern.get("business_id", ""),
        pattern.get("micro_market", ""),
        pattern.get("offer_name", ""),
        pattern.get("payer", ""),
        pattern.get("lp_url", ""),
        now,
        pattern.get("pattern_type", ""),
        json.dumps({
            "total_inquiries": pattern.get("total_inquiries", 0),
            "deals_won": pattern.get("deals_won", 0),
            "deal_rate": pattern.get("deal_rate", 0),
            "total_deal_value": pattern.get("total_deal_value", 0),
            "days_active": pattern.get("days_active", 0),
        }, ensure_ascii=False),
        json.dumps(sop, ensure_ascii=False),
        json.dumps(budget_rec, ensure_ascii=False),
        "detected",
        "initial",
    ]

    append_rows("winning_patterns", [row])
    logger.info(f"Saved winning pattern: {pattern_id} ({pattern.get('micro_market', '')})")
    return pattern_id


def log_expansion_action(
    pattern_id: str,
    business_id: str,
    action_type: str,
    action_detail: str,
    result: str = "",
) -> None:
    """Log an expansion action to expansion_log."""
    log_id = f"exp_{uuid.uuid4().hex[:8]}"
    now = datetime.now().isoformat()

    append_rows("expansion_log", [[
        log_id,
        pattern_id,
        business_id,
        action_type,
        action_detail,
        now,
        result,
    ]])
