"""
Cloud Scheduler client — list, pause, resume, and trigger jobs.
"""

from __future__ import annotations

from google.cloud import scheduler_v1

from agent.config import GCP_PROJECT_ID, GCP_REGION, get_logger, get_gcp_credentials

logger = get_logger(__name__)

_client: scheduler_v1.CloudSchedulerClient | None = None

SCOPES = ["https://www.googleapis.com/auth/cloud-scheduler"]


def _get_client() -> scheduler_v1.CloudSchedulerClient:
    global _client
    if _client is None:
        creds = get_gcp_credentials(scopes=SCOPES)
        _client = scheduler_v1.CloudSchedulerClient(credentials=creds)
    return _client


def _parent() -> str:
    return f"projects/{GCP_PROJECT_ID}/locations/{GCP_REGION}"


def list_jobs() -> list[dict]:
    """
    List all Cloud Scheduler jobs in the project/region.

    Returns:
        List of dicts with keys: name, schedule, state, description.
    """
    client = _get_client()
    parent = _parent()
    logger.info("Listing scheduler jobs in %s", parent)

    jobs = []
    for job in client.list_jobs(parent=parent):
        jobs.append({
            "name": job.name.split("/")[-1],
            "full_name": job.name,
            "schedule": job.schedule,
            "state": scheduler_v1.Job.State(job.state).name,
            "description": job.description or "",
            "time_zone": job.time_zone,
        })

    logger.info("Found %d scheduler jobs", len(jobs))
    return jobs


def pause_job(job_name: str) -> dict:
    """
    Pause a Cloud Scheduler job.

    Args:
        job_name: Short name (e.g. 'run-A-market-research') or full resource name.

    Returns:
        Dict with name and new state.
    """
    client = _get_client()
    full_name = _resolve_name(job_name)
    logger.info("Pausing job: %s", full_name)

    job = client.pause_job(name=full_name)
    return {
        "name": job.name.split("/")[-1],
        "state": scheduler_v1.Job.State(job.state).name,
    }


def resume_job(job_name: str) -> dict:
    """
    Resume a paused Cloud Scheduler job.

    Args:
        job_name: Short name or full resource name.

    Returns:
        Dict with name and new state.
    """
    client = _get_client()
    full_name = _resolve_name(job_name)
    logger.info("Resuming job: %s", full_name)

    job = client.resume_job(name=full_name)
    return {
        "name": job.name.split("/")[-1],
        "state": scheduler_v1.Job.State(job.state).name,
    }


def trigger_job(job_name: str) -> str:
    """
    Trigger a Cloud Scheduler job to run immediately.

    Args:
        job_name: Short name or full resource name.

    Returns:
        Confirmation message.
    """
    client = _get_client()
    full_name = _resolve_name(job_name)
    logger.info("Triggering job: %s", full_name)

    client.run_job(name=full_name)
    return f"Triggered {job_name} successfully"


def _resolve_name(job_name: str) -> str:
    """Resolve a short job name to its full resource name."""
    if job_name.startswith("projects/"):
        return job_name
    return f"{_parent()}/jobs/{job_name}"
