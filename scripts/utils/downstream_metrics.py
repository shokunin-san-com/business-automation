"""
Downstream metrics — aggregate inquiry + deal data into daily KPIs.

Used by analytics_reporter and learning_engine to track
CEO-priority metrics: test conversion rate, target customer rate, deal rate.
"""
from __future__ import annotations

import logging
from datetime import datetime

from utils.sheets_client import get_all_rows, append_row, find_row_index, update_cell, get_worksheet

logger = logging.getLogger(__name__)


def aggregate_daily_downstream(target_date: str | None = None) -> dict:
    """Aggregate inquiry_log + deal_pipeline into daily downstream KPI.

    Args:
        target_date: YYYY-MM-DD string. Defaults to today.

    Returns:
        Dict of aggregated KPI values.
    """
    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")

    inquiries = get_all_rows("inquiry_log")
    deals = get_all_rows("deal_pipeline")

    # Filter by date prefix (inquiries created today)
    day_inquiries = [r for r in inquiries if r.get("timestamp", "").startswith(target_date)]
    # All deals (cumulative pipeline)
    all_deals = deals

    total_inquiries = len(day_inquiries)
    qualified = [r for r in day_inquiries if r.get("status") == "qualified"]
    qualified_inquiries = len(qualified)

    proposals = [r for r in all_deals if r.get("stage") == "proposal"]
    won = [r for r in all_deals if r.get("stage") == "won"]
    lost = [r for r in all_deals if r.get("stage") == "lost"]

    total_deal_value = sum(float(r.get("deal_value", 0) or 0) for r in won)
    total_inq_all_time = len(inquiries)

    # CEO priority metrics
    test_conversion_rate = round(len(won) / total_inq_all_time, 4) if total_inq_all_time > 0 else 0
    target_customer_rate = round(qualified_inquiries / total_inquiries, 4) if total_inquiries > 0 else 0
    deal_rate = round(len(won) / max(len(won) + len(lost), 1), 4)

    kpi = {
        "date": target_date,
        "total_inquiries": total_inquiries,
        "qualified_inquiries": qualified_inquiries,
        "proposals_sent": len(proposals),
        "deals_won": len(won),
        "deals_lost": len(lost),
        "total_deal_value": total_deal_value,
        "test_conversion_rate": test_conversion_rate,
        "target_customer_rate": target_customer_rate,
        "deal_rate": deal_rate,
    }

    # Write to downstream_kpi sheet (upsert by date)
    try:
        _upsert_downstream_kpi(target_date, kpi)
    except Exception as e:
        logger.warning(f"Failed to write downstream_kpi: {e}")

    return kpi


def _upsert_downstream_kpi(target_date: str, kpi: dict) -> None:
    """Upsert a row in downstream_kpi sheet."""
    row_idx = find_row_index("downstream_kpi", "date", target_date)
    if row_idx:
        # Update existing row
        ws = get_worksheet("downstream_kpi")
        headers = ws.row_values(1)
        col_map = {h: i + 1 for i, h in enumerate(headers)}

        import gspread
        cells = []
        for key, val in kpi.items():
            if key in col_map and key != "date":
                cells.append(gspread.Cell(row=row_idx, col=col_map[key], value=str(val)))
        if cells:
            ws.update_cells(cells, value_input_option="USER_ENTERED")
    else:
        # Append new row
        append_row("downstream_kpi", [
            "",  # business_id (aggregate)
            target_date,
            "",  # run_id
            kpi["total_inquiries"],
            kpi["qualified_inquiries"],
            kpi["proposals_sent"],
            kpi["deals_won"],
            kpi["deals_lost"],
            kpi["total_deal_value"],
            kpi["test_conversion_rate"],
            kpi["target_customer_rate"],
            kpi["deal_rate"],
        ])


def get_latest_downstream_kpis(business_id: str | None = None) -> dict:
    """Get the most recent downstream KPI row.

    Args:
        business_id: Optional filter. If None, returns aggregate KPIs.

    Returns:
        Dict of latest KPI values or empty dict.
    """
    try:
        rows = get_all_rows("downstream_kpi")
        if business_id:
            rows = [r for r in rows if r.get("business_id") == business_id]
        if not rows:
            return {}
        # Latest by date
        rows.sort(key=lambda r: r.get("date", ""), reverse=True)
        row = rows[0]
        return {
            "date": row.get("date", ""),
            "total_inquiries": int(row.get("total_inquiries", 0) or 0),
            "qualified_inquiries": int(row.get("qualified_inquiries", 0) or 0),
            "proposals_sent": int(row.get("proposals_sent", 0) or 0),
            "deals_won": int(row.get("deals_won", 0) or 0),
            "deals_lost": int(row.get("deals_lost", 0) or 0),
            "total_deal_value": float(row.get("total_deal_value", 0) or 0),
            "test_conversion_rate": float(row.get("test_conversion_rate", 0) or 0),
            "target_customer_rate": float(row.get("target_customer_rate", 0) or 0),
            "deal_rate": float(row.get("deal_rate", 0) or 0),
        }
    except Exception as e:
        logger.warning(f"Failed to read downstream_kpi: {e}")
        return {}
