"""
History Writer — records agent execution results to agent_history sheet.

Each agent run produces a row with:
  - timestamp, task, duration, tool_calls_count, consistency_score,
    errors, final_response_summary
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json

import gspread

from agent.config import GOOGLE_SHEETS_ID, get_logger, get_gcp_credentials

logger = get_logger(__name__)

# Japan timezone offset
JST = timezone(timedelta(hours=9))

SHEET_NAME = "agent_history"
HEADERS = [
    "timestamp",
    "task",
    "duration_seconds",
    "turns_used",
    "tool_calls_count",
    "consistency_score",
    "errors",
    "response_summary",
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_gc: gspread.Client | None = None
_spreadsheet: gspread.Spreadsheet | None = None


def _get_spreadsheet() -> gspread.Spreadsheet:
    """Get or create spreadsheet handle (read-write for history)."""
    global _gc, _spreadsheet
    if _spreadsheet is None:
        creds = get_gcp_credentials(scopes=SCOPES)
        _gc = gspread.authorize(creds)
        _spreadsheet = _gc.open_by_key(GOOGLE_SHEETS_ID)
    return _spreadsheet


def _ensure_sheet() -> gspread.Worksheet:
    """Create agent_history sheet if it doesn't exist."""
    sp = _get_spreadsheet()
    try:
        ws = sp.worksheet(SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sp.add_worksheet(title=SHEET_NAME, rows=1000, cols=len(HEADERS))
        ws.append_row(HEADERS, value_input_option="USER_ENTERED")
        # Format header row
        ws.format("A1:H1", {
            "backgroundColor": {"red": 0.267, "green": 0.447, "blue": 0.769},
            "textFormat": {
                "bold": True,
                "foregroundColor": {"red": 1, "green": 1, "blue": 1},
            },
            "horizontalAlignment": "CENTER",
        })
        logger.info("Created agent_history sheet")
    return ws


def record_run(
    task: str,
    duration_seconds: float,
    turns_used: int,
    tool_calls_count: int,
    consistency_score: int | None,
    errors: list[str],
    response_summary: str,
) -> None:
    """
    Record an agent execution to the agent_history sheet.

    Args:
        task: The task/instruction given to the agent.
        duration_seconds: Total execution time in seconds.
        turns_used: Number of API round-trips used.
        tool_calls_count: Total number of tool calls made.
        consistency_score: Consistency check score (0-100), or None if not run.
        errors: List of error messages encountered.
        response_summary: Brief summary of the agent's response (truncated).
    """
    ws = _ensure_sheet()

    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    row = [
        now,
        task[:200],  # Truncate long tasks
        round(duration_seconds, 1),
        turns_used,
        tool_calls_count,
        consistency_score if consistency_score is not None else "",
        json.dumps(errors, ensure_ascii=False) if errors else "",
        response_summary[:500],  # Truncate long responses
    ]

    ws.append_row(row, value_input_option="USER_ENTERED")
    logger.info(
        "Recorded agent run: task=%s, duration=%.1fs, score=%s",
        task[:50],
        duration_seconds,
        consistency_score,
    )


def get_recent_runs(limit: int = 20) -> list[dict]:
    """
    Get recent agent runs from the history sheet.

    Args:
        limit: Maximum number of runs to return.

    Returns:
        List of dicts, most recent first.
    """
    ws = _ensure_sheet()
    records = ws.get_all_records()

    # Return most recent first
    return list(reversed(records[-limit:]))
