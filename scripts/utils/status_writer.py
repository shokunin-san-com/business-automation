"""
Status writer — records execution status of each script.

Cloud mode: writes to Google Sheets 'pipeline_status' sheet.
Local fallback: also writes to local JSON file for debugging.
Slack notifications: automatically sent on start/success/error.
"""
from __future__ import annotations

import json
import time
import logging
from datetime import datetime
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DATA_DIR

STATUS_FILE = DATA_DIR / "pipeline_status.json"

# --- Script labels (Japanese) for Slack notifications ---
SCRIPT_LABELS: dict[str, str] = {
    "orchestrate_v2": "🔬 V2パイプライン",
    "1_lp_generator": "🌐 LP生成",
    "2_sns_poster": "📱 SNS投稿",
    "3_form_sales": "📧 フォーム営業",
    "4_analytics_reporter": "📊 分析・改善",
    "5_slack_reporter": "📋 Slackレポート",
}

# Status → emoji + label
STATUS_DISPLAY: dict[str, str] = {
    "running": "▶️ 開始",
    "success": "✅ 完了",
    "error": "❌ エラー",
}


def _read_status() -> dict:
    if STATUS_FILE.exists():
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"scripts": {}, "last_updated": ""}


def _write_status(data: dict) -> None:
    data["last_updated"] = datetime.now().isoformat()
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # seconds


def _sheets_upsert_with_retry(
    script_name: str,
    status: str,
    detail: str,
    metrics_json: str,
    now: str,
) -> None:
    """Single attempt to upsert status to Sheets. Raises on failure."""
    from utils.sheets_client import (
        find_row_index,
        update_cell,
        append_row,
        get_worksheet,
    )

    row_idx = find_row_index("pipeline_status", "script_name", script_name)
    if row_idx:
        # Update existing row — batch into one request to reduce API calls
        ws = get_worksheet("pipeline_status")
        headers = ws.row_values(1)
        col_map = {h: i + 1 for i, h in enumerate(headers)}
        values = []
        if "status" in col_map:
            values.append(gspread_cell(row_idx, col_map["status"], status))
        if "detail" in col_map:
            values.append(gspread_cell(row_idx, col_map["detail"], detail))
        if "metrics_json" in col_map:
            values.append(gspread_cell(row_idx, col_map["metrics_json"], metrics_json))
        if "timestamp" in col_map:
            values.append(gspread_cell(row_idx, col_map["timestamp"], now))
        if values:
            ws.update_cells(values, value_input_option="USER_ENTERED")
    else:
        # Append new row
        append_row("pipeline_status", [
            script_name,
            status,
            detail,
            metrics_json,
            now,
        ])


def gspread_cell(row: int, col: int, value: str):
    """Create a gspread Cell object for batch update."""
    import gspread
    cell = gspread.Cell(row=row, col=col, value=value)
    return cell


def _write_to_sheets(
    script_name: str,
    status: str,
    detail: str,
    metrics: dict | None,
) -> None:
    """Upsert status to Google Sheets 'pipeline_status' sheet.

    Retries up to MAX_RETRIES times with exponential backoff on 429 errors.
    Also batches cell updates into a single API call to reduce quota usage.
    """
    _logger = logging.getLogger(__name__)
    now = datetime.now().isoformat()
    metrics_json = json.dumps(metrics or {}, ensure_ascii=False)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _sheets_upsert_with_retry(script_name, status, detail, metrics_json, now)
            return  # Success
        except Exception as e:
            is_rate_limit = "429" in str(e) or "Quota exceeded" in str(e)
            if is_rate_limit and attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))  # 2s, 4s
                _logger.warning(
                    f"Sheets API rate limit (attempt {attempt}/{MAX_RETRIES}), "
                    f"retrying in {delay}s: {e}"
                )
                time.sleep(delay)
            else:
                # Final attempt failed or non-retryable error — log and continue
                _logger.warning(f"Failed to write status to Sheets: {e}")
                return


def _notify_slack(
    script_name: str,
    status: str,
    detail: str,
) -> None:
    """Send a Slack notification for pipeline status changes.

    Only notifies on: running (first call = start), success, error.
    Intermediate 'running' updates (progress messages) are skipped.
    """
    # Only notify on meaningful transitions
    if status not in ("running", "success", "error"):
        return

    # For 'running': only notify the first call (start), skip progress updates
    if status == "running":
        data = _read_status()
        prev = data.get("scripts", {}).get(script_name, {})
        if prev.get("status") == "running":
            # Already running — this is a progress update, skip Slack
            return

    try:
        from utils.slack_notifier import send_message

        label = SCRIPT_LABELS.get(script_name, script_name)
        status_text = STATUS_DISPLAY.get(status, status)
        detail_part = f"\n> {detail}" if detail else ""

        text = f"{label} {status_text}{detail_part}"
        send_message(text)
    except Exception:
        # Slack notification is best-effort — never block pipeline
        pass


def update_status(
    script_name: str,
    status: str,
    detail: str = "",
    metrics: dict | None = None,
) -> None:
    """Update the execution status of a script.

    Args:
        script_name: e.g. "0_idea_generator"
        status: "running" | "success" | "error" | "idle"
        detail: Optional detail message
        metrics: Optional dict of metrics produced in this run
    """
    # Send Slack notification (before updating local status for start detection)
    _notify_slack(script_name, status, detail)

    # Always write local JSON (for debugging / backward compatibility)
    data = _read_status()
    data["scripts"][script_name] = {
        "status": status,
        "detail": detail,
        "metrics": metrics or {},
        "timestamp": datetime.now().isoformat(),
    }
    _write_status(data)

    # Also write to Google Sheets (best-effort)
    _write_to_sheets(script_name, status, detail, metrics)


def get_all_status() -> dict:
    """Read the full status file."""
    return _read_status()
