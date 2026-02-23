"""
Cloud Logging reader — fetches recent logs from Cloud Run Jobs.
"""

from __future__ import annotations

from google.cloud import logging as cloud_logging

from agent.config import GCP_PROJECT_ID, get_logger, get_gcp_credentials

logger = get_logger(__name__)

_client: cloud_logging.Client | None = None

SCOPES = ["https://www.googleapis.com/auth/logging.read"]


def _get_client() -> cloud_logging.Client:
    global _client
    if _client is None:
        creds = get_gcp_credentials(scopes=SCOPES)
        _client = cloud_logging.Client(project=GCP_PROJECT_ID, credentials=creds)
    return _client


def read_logs(
    job_name: str = "",
    severity: str = "ERROR",
    minutes: int = 60,
    limit: int = 50,
) -> list[dict]:
    """
    Read Cloud Run Job logs from Cloud Logging.

    Args:
        job_name: Filter by Cloud Run job name (e.g. 'marketprobe-pipeline').
                  Empty string means all jobs.
        severity: Minimum severity ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL').
        minutes: Look back this many minutes from now.
        limit: Maximum number of log entries to return.

    Returns:
        List of dicts with keys: timestamp, severity, message, job_name.
    """
    client = _get_client()

    # Build filter
    filters = [
        'resource.type="cloud_run_job"',
        f"severity>={severity}",
        f'timestamp>="{_minutes_ago(minutes)}"',
    ]
    if job_name:
        filters.append(
            f'resource.labels.job_name="{job_name}"'
        )

    filter_str = " AND ".join(filters)
    logger.info("Reading logs: %s (limit=%d)", filter_str, limit)

    entries = []
    for entry in client.list_entries(
        filter_=filter_str,
        order_by=cloud_logging.DESCENDING,
        max_results=limit,
        resource_names=[f"projects/{GCP_PROJECT_ID}"],
    ):
        entries.append({
            "timestamp": str(entry.timestamp),
            "severity": entry.severity,
            "message": entry.payload
            if isinstance(entry.payload, str)
            else str(entry.payload),
            "job_name": getattr(entry.resource, "labels", {}).get(
                "job_name", ""
            ),
        })

    logger.info("Found %d log entries", len(entries))
    return entries


def check_execution_logs(execution_name: str) -> str:
    """
    Check Cloud Run Job execution status via Cloud Logging.

    Searches for completion markers in the execution's logs.

    Args:
        execution_name: The execution name (short name or full resource path).

    Returns:
        'SUCCEEDED', 'FAILED', or 'RUNNING'.
    """
    client = _get_client()

    # Extract short execution name if full path given
    short_name = execution_name.split("/")[-1] if "/" in execution_name else execution_name

    filter_str = (
        'resource.type="cloud_run_job" '
        f'labels."run.googleapis.com/execution_name"="{short_name}"'
    )

    logger.info("Checking execution logs for: %s", short_name)

    try:
        entries = list(client.list_entries(
            filter_=filter_str,
            order_by=cloud_logging.DESCENDING,
            max_results=50,
            resource_names=[f"projects/{GCP_PROJECT_ID}"],
        ))

        for entry in entries:
            msg = str(getattr(entry, "payload", ""))
            severity = getattr(entry, "severity", "")
            if "Job execution finished" in msg or "completed" in msg.lower():
                return "FAILED" if severity in ("ERROR", "CRITICAL") else "SUCCEEDED"

        return "RUNNING"

    except Exception as e:
        logger.warning("Failed to check execution logs: %s", e)
        return "RUNNING"


def _minutes_ago(minutes: int) -> str:
    """Return ISO 8601 timestamp for `minutes` ago."""
    from datetime import datetime, timedelta, timezone

    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
