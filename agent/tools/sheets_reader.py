"""
Google Sheets reader — read-only access to pipeline data.
"""

from __future__ import annotations

import gspread

from agent.config import GOOGLE_SHEETS_ID, get_logger, get_gcp_credentials

logger = get_logger(__name__)

_gc: gspread.Client | None = None
_spreadsheet: gspread.Spreadsheet | None = None

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _get_spreadsheet() -> gspread.Spreadsheet:
    """Get or create the shared spreadsheet handle."""
    global _gc, _spreadsheet
    if _spreadsheet is None:
        creds = get_gcp_credentials(scopes=SCOPES)
        _gc = gspread.authorize(creds)
        _spreadsheet = _gc.open_by_key(GOOGLE_SHEETS_ID)
        logger.info("Connected to spreadsheet: %s", GOOGLE_SHEETS_ID)
    return _spreadsheet


def read_sheet(
    sheet_name: str,
    row_limit: int = 100,
) -> list[dict]:
    """
    Read rows from a Google Sheets tab as list of dicts.

    Args:
        sheet_name: Name of the worksheet tab (e.g. 'settings',
                    'market_research', 'business_ideas').
        row_limit: Maximum number of rows to return (default 100).

    Returns:
        List of dicts, one per row. Keys are column headers.
        Returns empty list if the sheet doesn't exist.
    """
    sp = _get_spreadsheet()

    try:
        ws = sp.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        logger.warning("Sheet '%s' not found", sheet_name)
        return []

    records = ws.get_all_records()
    logger.info(
        "Read %d rows from '%s' (limit=%d)",
        len(records),
        sheet_name,
        row_limit,
    )

    return records[:row_limit]


def list_sheets() -> list[str]:
    """
    List all worksheet tab names in the spreadsheet.

    Returns:
        List of sheet names.
    """
    sp = _get_spreadsheet()
    names = [ws.title for ws in sp.worksheets()]
    logger.info("Found %d sheets: %s", len(names), names)
    return names
