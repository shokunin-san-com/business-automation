"""
API call cost tracking — record usage and enforce monthly budget gates.

Records each API call to the cost_tracking sheet and checks cumulative
spend against configurable warning / hard-stop thresholds (JPY).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_logger

logger = get_logger(__name__)

JST = timezone(timedelta(hours=9))

# Gemini 2.5 Flash pricing (USD per 1M tokens, as of 2025-06)
# Under 200k context:  input $0.15, output $1.00 (non-thinking), thinking $3.50
# Over 200k context:   input $0.30, output $2.00 (non-thinking), thinking $7.00
# We use a simplified model: average blended rate
PRICE_PER_1M_INPUT = 0.15
PRICE_PER_1M_OUTPUT = 1.00
PRICE_PER_SEARCH_GROUNDING = 0.0035  # per request with grounding

USD_JPY_RATE = 150  # approximate


def _estimate_cost_jpy(
    input_tokens: int = 0,
    output_tokens: int = 0,
    used_search: bool = False,
) -> float:
    cost_usd = (
        (input_tokens / 1_000_000) * PRICE_PER_1M_INPUT
        + (output_tokens / 1_000_000) * PRICE_PER_1M_OUTPUT
    )
    if used_search:
        cost_usd += PRICE_PER_SEARCH_GROUNDING
    return round(cost_usd * USD_JPY_RATE, 2)


def record_api_call(
    run_id: str,
    phase: str,
    api_name: str = "gemini",
    input_tokens: int = 0,
    output_tokens: int = 0,
    used_search: bool = False,
    note: str = "",
) -> float:
    from utils.sheets_client import append_rows

    cost_jpy = _estimate_cost_jpy(input_tokens, output_tokens, used_search)
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")

    row = [
        run_id,
        now,
        phase,
        api_name,
        input_tokens,
        output_tokens,
        "Y" if used_search else "N",
        cost_jpy,
        note,
    ]
    try:
        append_rows("cost_tracking", [row])
    except Exception as e:
        logger.warning(f"Failed to write cost_tracking row: {e}")

    return cost_jpy


def get_monthly_cumulative_jpy() -> float:
    from utils.sheets_client import get_all_rows

    now = datetime.now(JST)
    month_prefix = now.strftime("%Y-%m")

    try:
        rows = get_all_rows("cost_tracking")
    except Exception as e:
        logger.warning(f"Failed to read cost_tracking: {e}")
        return 0.0

    total = 0.0
    for r in rows:
        ts = r.get("timestamp", "")
        if ts.startswith(month_prefix):
            try:
                total += float(r.get("cost_jpy", 0))
            except (ValueError, TypeError):
                pass
    return round(total, 2)


def check_budget_gate(
    warn_jpy: Optional[float] = None,
    hard_stop_jpy: Optional[float] = None,
) -> dict:
    from utils.sheets_client import get_setting

    if warn_jpy is None:
        try:
            warn_jpy = float(get_setting("cost_warn_jpy") or 25000)
        except (ValueError, TypeError):
            warn_jpy = 25000
    if hard_stop_jpy is None:
        try:
            hard_stop_jpy = float(get_setting("cost_hard_stop_jpy") or 30000)
        except (ValueError, TypeError):
            hard_stop_jpy = 30000

    cumulative = get_monthly_cumulative_jpy()

    result = {
        "cumulative_jpy": cumulative,
        "warn_jpy": warn_jpy,
        "hard_stop_jpy": hard_stop_jpy,
        "status": "OK",
    }

    if cumulative >= hard_stop_jpy:
        result["status"] = "HARD_STOP"
        logger.error(
            f"BUDGET HARD STOP: ¥{cumulative:,.0f} >= ¥{hard_stop_jpy:,.0f}"
        )
    elif cumulative >= warn_jpy:
        result["status"] = "WARNING"
        logger.warning(
            f"BUDGET WARNING: ¥{cumulative:,.0f} >= ¥{warn_jpy:,.0f}"
        )
    else:
        logger.info(
            f"Budget OK: ¥{cumulative:,.0f} / ¥{hard_stop_jpy:,.0f}"
        )

    return result
