"""
Cloud Build client — trigger builds via REST API.

Uses the Cloud Build REST API directly (via ``requests``) instead of
the google-cloud-build SDK, keeping the agent container lightweight.
"""

from __future__ import annotations

import requests as _requests
from google.auth.transport.requests import Request as AuthRequest

from agent.config import GCP_PROJECT_ID, get_logger, get_gcp_credentials

logger = get_logger(__name__)

CLOUDBUILD_API = "https://cloudbuild.googleapis.com/v1"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


def _get_access_token() -> str:
    """Get an OAuth2 access token for the Cloud Build API."""
    creds = get_gcp_credentials(scopes=SCOPES)
    creds.refresh(AuthRequest())
    return creds.token


def trigger_build(
    config_file: str = "cloudbuild-agent.yaml",
    substitutions: dict | None = None,
) -> dict:
    """
    Trigger a Cloud Build.

    Currently fires a build using the Cloud Source Repositories mirror of
    the ``business-automation`` repo.  If a ``cloudbuild.yaml`` (pipeline)
    or ``cloudbuild-agent.yaml`` (agent) trigger is configured, the build
    picks up the steps from that file automatically.

    Args:
        config_file:   Path to the cloudbuild config in the repo.
                       ``"cloudbuild-agent.yaml"`` (agent container) or
                       ``"cloudbuild.yaml"`` (pipeline container).
        substitutions: Optional substitution variables for the build.

    Returns:
        Dict with keys: build_id, status, log_url.
    """
    token = _get_access_token()
    url = f"{CLOUDBUILD_API}/projects/{GCP_PROJECT_ID}/builds"

    body: dict = {
        "source": {
            "repoSource": {
                "projectId": GCP_PROJECT_ID,
                "repoName": "business-automation",
                "branchName": "main",
            },
        },
        "filename": config_file,
    }
    if substitutions:
        body["substitutions"] = substitutions

    resp = _requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    build_meta = data.get("metadata", {}).get("build", {})
    build_id = build_meta.get("id", data.get("name", ""))
    log_url = build_meta.get("logUrl", "")

    logger.info("Cloud Build triggered: build_id=%s, config=%s", build_id, config_file)
    return {
        "build_id": build_id,
        "status": "QUEUED",
        "log_url": log_url,
    }
