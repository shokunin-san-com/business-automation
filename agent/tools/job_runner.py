"""
Cloud Run Jobs runner — start V2 pipeline jobs on demand.

V2 pipeline script → Cloud Run Job mapping:
  orchestrate_v2       →  orchestrate-v2
  1_lp_generator       →  lp-generator
  2_sns_poster         →  sns-poster
  3_form_sales         →  form-sales
  4_analytics_reporter →  analytics-reporter
  5_slack_reporter     →  slack-reporter
  7_learning_engine    →  learning-engine
  9_expansion_engine   →  expansion-engine

V1 scripts (A/B/C/0/orchestrate_abc0, 6_ads_monitor, 8_ads_creator) are DEPRECATED.
"""

from __future__ import annotations

from google.cloud import run_v2

from agent.config import GCP_PROJECT_ID, GCP_REGION, get_logger, get_gcp_credentials

logger = get_logger(__name__)

_client: run_v2.JobsClient | None = None

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

# Maps SCRIPT_NAME → Cloud Run Job name
# V2パイプライン専用（V1ジョブは完全廃止）
SCRIPT_TO_JOB = {
    "orchestrate_v2": "orchestrate-v2",
    "1_lp_generator": "lp-generator",
    "2_sns_poster": "sns-poster",
    "3_form_sales": "form-sales",
    "4_analytics_reporter": "analytics-reporter",
    "5_slack_reporter": "slack-reporter",
    "7_learning_engine": "learning-engine",
    "9_expansion_engine": "expansion-engine",
}


def _get_client() -> run_v2.JobsClient:
    global _client
    if _client is None:
        creds = get_gcp_credentials(scopes=SCOPES)
        _client = run_v2.JobsClient(credentials=creds)
    return _client


def run_job(script_name: str) -> dict:
    """
    Run a Cloud Run Job for the given script.

    If the script has a dedicated Cloud Run Job, it runs that job directly.

    For scripts without a dedicated job, it uses orchestrate-v2 job with
    a SCRIPT_NAME environment variable override.

    Args:
        script_name: The V2 script key from SCRIPT_MAP in run.py,
                     e.g. 'orchestrate_v2', '1_lp_generator'.

    Returns:
        Dict with execution_name, script_name, job_name, and status.
    """
    client = _get_client()

    # Determine which Cloud Run Job to use
    if script_name in SCRIPT_TO_JOB:
        # Dedicated job — run directly (no override needed)
        cloud_run_job_name = SCRIPT_TO_JOB[script_name]
        use_override = False
    else:
        # No dedicated job — use orchestrate-v2 with SCRIPT_NAME override
        cloud_run_job_name = "orchestrate-v2"
        use_override = True

    job_full_name = (
        f"projects/{GCP_PROJECT_ID}/locations/{GCP_REGION}"
        f"/jobs/{cloud_run_job_name}"
    )

    logger.info(
        "Starting Cloud Run Job '%s' (script=%s, override=%s)",
        cloud_run_job_name,
        script_name,
        use_override,
    )

    if use_override:
        # Override SCRIPT_NAME for scripts without dedicated jobs
        request = run_v2.RunJobRequest(
            name=job_full_name,
            overrides=run_v2.RunJobRequest.Overrides(
                container_overrides=[
                    run_v2.RunJobRequest.Overrides.ContainerOverride(
                        env=[
                            run_v2.EnvVar(
                                name="SCRIPT_NAME",
                                value=script_name,
                            )
                        ]
                    )
                ]
            ),
        )
    else:
        # Direct run — job already has SCRIPT_NAME configured
        request = run_v2.RunJobRequest(name=job_full_name)

    operation = client.run_job(request=request)
    logger.info("Job started: operation=%s", operation.operation.name)

    return {
        "execution_name": operation.operation.name,
        "script_name": script_name,
        "job_name": cloud_run_job_name,
        "status": "started",
    }


def get_execution_status(execution_name: str) -> dict:
    """
    Get the status of a Cloud Run Job execution.

    Args:
        execution_name: Full resource name of the execution.

    Returns:
        Dict with name, status, create_time, completion_time.
    """
    creds = get_gcp_credentials(scopes=SCOPES)
    executions_client = run_v2.ExecutionsClient(credentials=creds)

    try:
        execution = executions_client.get_execution(name=execution_name)
        return {
            "name": execution.name,
            "status": _reconcile_status(execution),
            "create_time": str(execution.create_time),
            "completion_time": str(execution.completion_time)
            if execution.completion_time
            else None,
        }
    except Exception as e:
        logger.error("Failed to get execution status: %s", e)
        return {
            "name": execution_name,
            "status": "unknown",
            "error": str(e),
        }


def _reconcile_status(execution: run_v2.Execution) -> str:
    """Map execution conditions to a simple status string."""
    if execution.reconciling:
        return "running"
    for condition in execution.conditions:
        if condition.type_ == "Completed" and condition.state.name == "CONDITION_SUCCEEDED":
            return "succeeded"
        if condition.type_ == "Completed" and condition.state.name == "CONDITION_FAILED":
            return "failed"
    return "running"
