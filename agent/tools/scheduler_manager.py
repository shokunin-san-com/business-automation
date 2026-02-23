"""
Cloud Scheduler manager — create / update / delete scheduler jobs.

Complements scheduler_client.py (which only reads / pauses / resumes / triggers).
This module adds the ability to *create* new scheduler jobs programmatically
and to parse natural-language schedule descriptions into cron expressions.
"""

from __future__ import annotations

import re

from google.cloud import scheduler_v1
from google.protobuf import duration_pb2

from agent.config import GCP_PROJECT_ID, GCP_REGION, get_logger, get_gcp_credentials

logger = get_logger(__name__)

_client: scheduler_v1.CloudSchedulerClient | None = None
SCOPES = ["https://www.googleapis.com/auth/cloud-scheduler"]


# ── Internals ────────────────────────────────────────────────────


def _get_client() -> scheduler_v1.CloudSchedulerClient:
    global _client
    if _client is None:
        creds = get_gcp_credentials(scopes=SCOPES)
        _client = scheduler_v1.CloudSchedulerClient(credentials=creds)
    return _client


def _parent() -> str:
    return f"projects/{GCP_PROJECT_ID}/locations/{GCP_REGION}"


# ── Natural-language → cron parser ───────────────────────────────


# Japanese day-of-week map
_DOW_MAP = {"月": "1", "火": "2", "水": "3", "木": "4", "金": "5", "土": "6", "日": "0"}


def parse_schedule_from_text(text: str) -> str:
    """
    Parse a natural-language schedule description into a cron expression.

    Supported patterns (Japanese + English):
        "毎朝9時"          →  "0 9 * * *"
        "毎日14:30"        →  "30 14 * * *"
        "毎週月曜9時"      →  "0 9 * * 1"
        "every 3 hours"    →  "0 */3 * * *"
        "0 9 * * *"        →  pass through (already cron)

    Args:
        text: Natural language schedule or cron expression.

    Returns:
        Cron expression string (5 fields).

    Raises:
        ValueError: If the schedule text cannot be parsed.
    """
    stripped = text.strip()

    # Pass-through if already a valid cron expression (5 space-separated fields)
    if re.match(r"^[\d\*\/\-\,]+(\s+[\d\*\/\-\,]+){4}$", stripped):
        return stripped

    # "毎朝N時" / "毎日N時" / "毎晩N時" / "毎夜N時"
    m = re.search(r"毎(朝|日|晩|夜)(\d{1,2})時", text)
    if m:
        hour = int(m.group(2))
        return f"0 {hour} * * *"

    # "毎日HH:MM"
    m = re.search(r"毎日\s*(\d{1,2}):(\d{2})", text)
    if m:
        return f"{int(m.group(2))} {int(m.group(1))} * * *"

    # "毎週X曜N時" / "毎週X曜日N時"
    m = re.search(r"毎週(.)[曜日]*\s*(\d{1,2})時", text)
    if m:
        dow = _DOW_MAP.get(m.group(1), "1")
        hour = int(m.group(2))
        return f"0 {hour} * * {dow}"

    # "N時間おき" / "every N hours"
    m = re.search(r"(\d+)\s*(時間おき|hours?)", text, re.IGNORECASE)
    if m:
        hours = int(m.group(1))
        return f"0 */{hours} * * *"

    # "N分おき" / "every N minutes"
    m = re.search(r"(\d+)\s*(分おき|minutes?)", text, re.IGNORECASE)
    if m:
        minutes = int(m.group(1))
        return f"*/{minutes} * * * *"

    raise ValueError(f"スケジュールを解析できません: '{text}'")


# ── Public API ───────────────────────────────────────────────────


def register(
    job_name: str,
    schedule: str,
    target_job_id: str,
    description: str = "",
    time_zone: str = "Asia/Tokyo",
) -> dict:
    """
    Create or update a Cloud Scheduler job that triggers a Cloud Run Job.

    Args:
        job_name:      Short name for the scheduler job (e.g. "schedule-v2-morning").
        schedule:      Cron expression **or** natural-language (auto-parsed).
        target_job_id: Cloud Run Job ID to trigger (e.g. "market-research").
        description:   Optional description.
        time_zone:     Default: Asia/Tokyo.

    Returns:
        Dict with keys: name, schedule, state, time_zone.
    """
    client = _get_client()
    cron = parse_schedule_from_text(schedule)
    parent = _parent()
    full_name = f"{parent}/jobs/{job_name}"

    # Cloud Run Job target URL
    job_url = (
        f"https://{GCP_REGION}-run.googleapis.com/v2/"
        f"projects/{GCP_PROJECT_ID}/locations/{GCP_REGION}/"
        f"jobs/{target_job_id}:run"
    )

    job = scheduler_v1.Job(
        name=full_name,
        description=description or f"Auto-created by agent: trigger {target_job_id}",
        schedule=cron,
        time_zone=time_zone,
        http_target=scheduler_v1.HttpTarget(
            uri=job_url,
            http_method=scheduler_v1.HttpMethod.POST,
            oauth_token=scheduler_v1.OAuthToken(
                service_account_email=(
                    f"{GCP_PROJECT_ID}@appspot.gserviceaccount.com"
                ),
            ),
        ),
        retry_config=scheduler_v1.RetryConfig(
            retry_count=1,
            max_retry_duration=duration_pb2.Duration(seconds=0),
        ),
    )

    # Try update first, fall back to create
    try:
        result = client.update_job(job=job)
        logger.info("Updated scheduler job: %s → %s", job_name, cron)
    except Exception:
        result = client.create_job(parent=parent, job=job)
        logger.info("Created scheduler job: %s → %s", job_name, cron)

    return {
        "name": result.name.split("/")[-1],
        "schedule": result.schedule,
        "state": scheduler_v1.Job.State(result.state).name,
        "time_zone": result.time_zone,
    }


def delete_schedule(job_name: str) -> str:
    """
    Delete a Cloud Scheduler job.

    Args:
        job_name: Short name or full resource name.

    Returns:
        Confirmation message.
    """
    client = _get_client()
    full_name = (
        job_name
        if job_name.startswith("projects/")
        else f"{_parent()}/jobs/{job_name}"
    )
    client.delete_job(name=full_name)
    logger.info("Deleted scheduler job: %s", job_name)
    return f"Deleted scheduler job: {job_name}"
