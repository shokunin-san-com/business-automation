"""
Google Sheets client — read/write rows for the business automation spreadsheet.

Supports two auth methods:
  - OAuth (interactive, browser-based)
  - Service Account (automated, JSON key file)

Includes automatic retry with exponential backoff for rate limit (429) errors.
"""
from __future__ import annotations

import functools
import time
from typing import Any, Optional

import gspread
from google.oauth2.service_account import Credentials as SACredentials
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import GOOGLE_SHEETS_ID, CREDENTIALS_DIR, get_logger

logger = get_logger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_client: gspread.Client | None = None
_spreadsheet: gspread.Spreadsheet | None = None

# ---------------------------------------------------------------------------
# Retry decorator for Sheets API rate-limit (429) errors
# ---------------------------------------------------------------------------
SHEETS_MAX_RETRIES = 4
SHEETS_RETRY_BASE_DELAY = 2  # seconds


def _retry_on_rate_limit(func):
    """Decorator: retry with exponential backoff on Google Sheets 429 errors."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        last_exception = None
        for attempt in range(1, SHEETS_MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except gspread.exceptions.APIError as e:
                last_exception = e
                status_code = e.response.status_code if hasattr(e, "response") else 0
                if status_code == 429 and attempt < SHEETS_MAX_RETRIES:
                    delay = SHEETS_RETRY_BASE_DELAY * (2 ** (attempt - 1))  # 2, 4, 8s
                    logger.warning(
                        f"Sheets API rate limit (attempt {attempt}/{SHEETS_MAX_RETRIES}), "
                        f"retrying in {delay}s..."
                    )
                    time.sleep(delay)
                else:
                    raise
        # Safety net: should never reach here, but re-raise if it does
        if last_exception:
            raise last_exception

    return wrapper


def _authenticate_service_account() -> gspread.Client:
    import json
    import os

    # Try env var first (Cloud Run injects via Secret Manager)
    sa_json_env = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if sa_json_env:
        try:
            info = json.loads(sa_json_env, strict=False)
            creds = SACredentials.from_service_account_info(info, scopes=SCOPES)
            return gspread.authorize(creds)
        except Exception as e:
            logger.warning(f"Failed to auth from env var: {e}, trying file...")

    # Fallback to file
    sa_path = CREDENTIALS_DIR / "service_account.json"
    if not sa_path.exists():
        raise FileNotFoundError(
            f"Service account JSON not found: {sa_path}\n"
            "Place your GCP service account key there."
        )
    creds = SACredentials.from_service_account_file(str(sa_path), scopes=SCOPES)
    return gspread.authorize(creds)


def _authenticate_oauth() -> gspread.Client:
    token_path = CREDENTIALS_DIR / "token.pickle"
    creds_path = CREDENTIALS_DIR / "credentials.json"
    creds = None

    if token_path.exists():
        with open(token_path, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                raise FileNotFoundError(
                    f"OAuth credentials.json not found: {creds_path}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)

    return gspread.authorize(creds)


def get_client(auth_method: str = "service_account") -> gspread.Client:
    """Return an authenticated gspread client (cached)."""
    global _client
    if _client is None:
        if auth_method == "service_account":
            _client = _authenticate_service_account()
        else:
            _client = _authenticate_oauth()
        logger.info(f"Google Sheets authenticated ({auth_method})")
    return _client


def get_spreadsheet(auth_method: str = "service_account") -> gspread.Spreadsheet:
    """Return the main project spreadsheet (cached)."""
    global _spreadsheet
    if _spreadsheet is None:
        client = get_client(auth_method)
        _spreadsheet = client.open_by_key(GOOGLE_SHEETS_ID)
        logger.info(f"Opened spreadsheet: {_spreadsheet.title}")
    return _spreadsheet


def get_worksheet(sheet_name: str) -> gspread.Worksheet:
    """Get a worksheet by name from the main spreadsheet."""
    ss = get_spreadsheet()
    return ss.worksheet(sheet_name)


@_retry_on_rate_limit
def get_all_rows(sheet_name: str) -> list[dict[str, Any]]:
    """Return all rows from a sheet as a list of dicts."""
    ws = get_worksheet(sheet_name)
    try:
        return ws.get_all_records()
    except Exception as e:
        if "Expecting value" in str(e):
            # gspread raises JSONDecodeError when header/data columns mismatch
            # or when there are duplicate/empty headers. Fall back to manual parse.
            logger.warning(f"get_all_records() failed for {sheet_name}: {e}. Using fallback.")
            data = ws.get_all_values()
            if len(data) < 2:
                return []
            headers = data[0]
            # Deduplicate empty headers by adding index suffix
            seen: dict[str, int] = {}
            clean_headers = []
            for h in headers:
                h = str(h).strip()
                if not h:
                    h = f"_col_{len(clean_headers)}"
                if h in seen:
                    seen[h] += 1
                    h = f"{h}_{seen[h]}"
                else:
                    seen[h] = 0
                clean_headers.append(h)
            rows = []
            for row_data in data[1:]:
                if all(str(c).strip() == "" for c in row_data):
                    continue
                row_dict = {}
                for i, header in enumerate(clean_headers):
                    row_dict[header] = row_data[i] if i < len(row_data) else ""
                rows.append(row_dict)
            return rows
        raise


def get_rows_by_status(sheet_name: str, status: str) -> list[dict[str, Any]]:
    """Return rows where the 'status' column matches the given value."""
    rows = get_all_rows(sheet_name)
    return [r for r in rows if r.get("status") == status]


@_retry_on_rate_limit
def append_row(sheet_name: str, row: list[Any]) -> None:
    """Append a single row to the end of a sheet."""
    ws = get_worksheet(sheet_name)
    ws.append_row(row, value_input_option="USER_ENTERED")
    logger.info(f"Appended row to {sheet_name}")


@_retry_on_rate_limit
def append_rows(sheet_name: str, rows: list[list[Any]]) -> None:
    """Append multiple rows at once."""
    ws = get_worksheet(sheet_name)
    ws.append_rows(rows, value_input_option="USER_ENTERED")
    logger.info(f"Appended {len(rows)} rows to {sheet_name}")


@_retry_on_rate_limit
def update_cell(sheet_name: str, row: int, col: int, value: Any) -> None:
    """Update a single cell (1-indexed row/col)."""
    ws = get_worksheet(sheet_name)
    ws.update_cell(row, col, value)


@_retry_on_rate_limit
def update_cell_by_key(
    sheet_name: str,
    key_column: str,
    key_value: str,
    target_column: str,
    target_value: Any,
) -> bool:
    """Update a cell by looking up a row where key_column == key_value.

    Sets target_column to target_value in the matching row.
    Returns True if the cell was updated, False if no match found.
    """
    ws = get_worksheet(sheet_name)
    headers = ws.row_values(1)
    if key_column not in headers or target_column not in headers:
        logger.warning(f"Column not found: {key_column} or {target_column} in {sheet_name}")
        return False

    key_col_idx = headers.index(key_column) + 1
    target_col_idx = headers.index(target_column) + 1

    col_values = ws.col_values(key_col_idx)
    for i, v in enumerate(col_values):
        if i == 0:
            continue  # skip header
        if v == key_value:
            ws.update_cell(i + 1, target_col_idx, target_value)
            return True

    logger.warning(f"No row found in {sheet_name} where {key_column}={key_value}")
    return False


@_retry_on_rate_limit
def batch_update_by_key(
    sheet_name: str,
    key_column: str,
    key_value: str,
    updates: dict[str, Any],
) -> bool:
    """Update multiple columns in one row matching key_column == key_value.

    Uses a single batch_update API call instead of N individual calls.
    Only 2 API reads (headers + key column) + 1 write = 3 total,
    regardless of how many columns are updated.

    Args:
        sheet_name: Sheet tab name
        key_column: Column to search in
        key_value: Value to match
        updates: Dict of {column_name: new_value} pairs

    Returns True if updated, False if not found.
    """
    ws = get_worksheet(sheet_name)
    headers = ws.row_values(1)

    if key_column not in headers:
        logger.warning(f"Key column '{key_column}' not found in {sheet_name}")
        return False

    # Validate all target columns exist
    for col in updates:
        if col not in headers:
            logger.warning(f"Target column '{col}' not found in {sheet_name}")
            return False

    key_col_idx = headers.index(key_column) + 1
    col_values = ws.col_values(key_col_idx)

    row_idx = None
    for i, v in enumerate(col_values):
        if i == 0:
            continue
        if v == key_value:
            row_idx = i + 1  # 1-indexed
            break

    if row_idx is None:
        logger.warning(f"No row in {sheet_name} where {key_column}={key_value}")
        return False

    # Build batch update cells list
    cells = []
    for col_name, value in updates.items():
        col_idx = headers.index(col_name) + 1
        cell = gspread.Cell(row=row_idx, col=col_idx, value=value)
        cells.append(cell)

    if cells:
        ws.update_cells(cells, value_input_option="USER_ENTERED")
        logger.info(f"Batch updated {len(cells)} cells in row {row_idx} of {sheet_name}")

    return True


@_retry_on_rate_limit
def find_row_index(sheet_name: str, column_name: str, value: str) -> int | None:
    """Find the 1-indexed row number where column_name == value.

    Returns None if not found.  Row 1 is the header.
    """
    ws = get_worksheet(sheet_name)
    headers = ws.row_values(1)
    if column_name not in headers:
        return None
    col_idx = headers.index(column_name) + 1

    col_values = ws.col_values(col_idx)
    for i, v in enumerate(col_values):
        if i == 0:
            continue  # skip header
        if v == value:
            return i + 1  # 1-indexed
    return None


def get_setting(key: str, default: str = "") -> str:
    """Read a single setting value from the 'settings' sheet.

    Returns default if key not found or sheet unavailable.
    """
    try:
        rows = get_all_rows("settings")
        for r in rows:
            if r.get("key") == key:
                return r.get("value", default) or default
    except Exception:
        pass
    return default


def get_sheet_url(sheet_name: str) -> str:
    """Return the direct URL for a specific sheet tab.

    Format: https://docs.google.com/spreadsheets/d/{ID}/edit#gid={GID}
    Returns empty string if sheet not found.
    """
    try:
        ss = get_spreadsheet()
        ws = ss.worksheet(sheet_name)
        return f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEETS_ID}/edit#gid={ws.id}"
    except Exception as e:
        logger.warning(f"Failed to get URL for sheet '{sheet_name}': {e}")
        return ""


def get_sheet_urls(sheet_names: list[str] | None = None) -> dict[str, str]:
    """Return a dict of {sheet_name: url} for the given sheets (or all sheets).

    Fetches all worksheet metadata in a single API call for efficiency.
    """
    ss = get_spreadsheet()
    urls: dict[str, str] = {}
    base = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEETS_ID}/edit#gid="
    for ws in ss.worksheets():
        if sheet_names is None or ws.title in sheet_names:
            urls[ws.title] = f"{base}{ws.id}"
    return urls


def ensure_sheet_exists(
    sheet_name: str, headers: list[str]
) -> gspread.Worksheet:
    """Create a sheet with headers if it doesn't exist yet."""
    ss = get_spreadsheet()
    try:
        ws = ss.worksheet(sheet_name)
        logger.info(f"Sheet already exists: {sheet_name}")
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=sheet_name, rows=1000, cols=len(headers))
        ws.append_row(headers, value_input_option="USER_ENTERED")
        # Format header row
        ws.format("A1:Z1", {
            "backgroundColor": {"red": 0.267, "green": 0.447, "blue": 0.769},
            "textFormat": {
                "bold": True,
                "foregroundColor": {"red": 1, "green": 1, "blue": 1},
            },
            "horizontalAlignment": "CENTER",
        })
        logger.info(f"Created sheet: {sheet_name}")
    return ws
