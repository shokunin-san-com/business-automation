"""
Gemini Function Calling definitions — tool schemas for the agent.

Each tool definition follows the Gemini protos.FunctionDeclaration format.
We define them as dicts and convert to protos at runtime.
"""

import google.generativeai as genai

# Raw definitions (JSON-Schema-like, same structure as before but adapted for Gemini)
_RAW_DEFINITIONS = [
    {
        "name": "read_logs",
        "description": (
            "Read Cloud Run Job logs from Cloud Logging. "
            "Use this to check for errors, warnings, or recent execution results "
            "from any pipeline job."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "job_name": {
                    "type": "STRING",
                    "description": (
                        "Cloud Run job name to filter logs. "
                        "Default: 'marketprobe-pipeline'. "
                        "Empty string returns logs from all jobs."
                    ),
                },
                "severity": {
                    "type": "STRING",
                    "description": "Minimum log severity to fetch. One of: DEBUG, INFO, WARNING, ERROR, CRITICAL. Default: 'ERROR'.",
                },
                "minutes": {
                    "type": "INTEGER",
                    "description": "How many minutes back to look. Default: 60.",
                },
                "limit": {
                    "type": "INTEGER",
                    "description": "Maximum number of log entries. Default: 50.",
                },
            },
        },
    },
    {
        "name": "list_scheduler_jobs",
        "description": (
            "List all Cloud Scheduler jobs with their schedule, state (ENABLED/PAUSED), "
            "and description. Use this to understand the current cron schedule."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        },
    },
    {
        "name": "pause_scheduler_job",
        "description": (
            "Pause a Cloud Scheduler job so it stops executing on its cron schedule. "
            "The job can be resumed later."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "job_name": {
                    "type": "STRING",
                    "description": "Short name of the scheduler job to pause.",
                },
            },
            "required": ["job_name"],
        },
    },
    {
        "name": "resume_scheduler_job",
        "description": "Resume a previously paused Cloud Scheduler job.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "job_name": {
                    "type": "STRING",
                    "description": "Short name of the scheduler job to resume.",
                },
            },
            "required": ["job_name"],
        },
    },
    {
        "name": "trigger_scheduler_job",
        "description": (
            "Trigger a Cloud Scheduler job to run immediately, "
            "regardless of its cron schedule."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "job_name": {
                    "type": "STRING",
                    "description": "Short name of the scheduler job to trigger.",
                },
            },
            "required": ["job_name"],
        },
    },
    {
        "name": "read_sheet",
        "description": (
            "Read data from a Google Sheets tab. Returns rows as a list of dicts. "
            "Available sheets include: settings, micro_market_list, gate_decision_log, "
            "competitor_20_log, offer_3_log, lp_ready_log, pipeline_status, "
            "inquiry_log, deal_pipeline, downstream_kpi, winning_patterns, and more."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "sheet_name": {
                    "type": "STRING",
                    "description": (
                        "Name of the worksheet tab to read "
                        "(e.g. 'settings', 'micro_market_list', 'gate_decision_log')."
                    ),
                },
                "row_limit": {
                    "type": "INTEGER",
                    "description": "Maximum number of rows to return. Default: 100.",
                },
            },
            "required": ["sheet_name"],
        },
    },
    {
        "name": "list_sheets",
        "description": "List all worksheet tab names in the pipeline spreadsheet.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        },
    },
    {
        "name": "run_pipeline_job",
        "description": (
            "Start a Cloud Run Job execution for a specific V2 pipeline script. "
            "Each script has its own Cloud Run Job. "
            "Available scripts and their jobs: "
            "orchestrate_v2 (orchestrate-v2), "
            "1_lp_generator (lp-generator — LP生成+ブログ自動トリガー), "
            "blog_generator (blog-generator — ブログ50記事生成、単体実行も可能), "
            "2_sns_poster (sns-poster — リアルタイムSNS投稿), "
            "sns_batch_generator (sns-batch-generator — SNS100投稿バッチ生成→sns_queue), "
            "sns_scheduled_poster (sns-scheduled-poster — sns_queueから毎日自動投稿), "
            "3_form_sales (form-sales), "
            "4_analytics_reporter (analytics-reporter), "
            "5_slack_reporter (slack-reporter), "
            "7_learning_engine (learning-engine), "
            "9_expansion_engine (expansion-engine). "
            "V1 scripts (A_market_research, B_market_selection, etc.) are DEPRECATED."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "script_name": {
                    "type": "STRING",
                    "description": (
                        "Script key from the V2 pipeline dispatcher. "
                        "Examples: 'orchestrate_v2', '1_lp_generator', "
                        "'blog_generator', 'sns_batch_generator', "
                        "'sns_scheduled_poster', '2_sns_poster', "
                        "'7_learning_engine', '9_expansion_engine'."
                    ),
                },
            },
            "required": ["script_name"],
        },
    },
    {
        "name": "get_execution_status",
        "description": (
            "Check the status of a running or completed Cloud Run Job execution. "
            "Returns status (running/succeeded/failed), creation time, "
            "and completion time."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "execution_name": {
                    "type": "STRING",
                    "description": "Full resource name of the execution to check.",
                },
            },
            "required": ["execution_name"],
        },
    },
    {
        "name": "get_github_file",
        "description": (
            "Get the contents of a file from the GitHub repository. "
            "Returns the file content (decoded text), SHA, and path."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "File path in the repository.",
                },
                "ref": {
                    "type": "STRING",
                    "description": "Branch or commit ref. Default: repo default branch.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "update_github_file",
        "description": (
            "Create or update a file in the GitHub repository. "
            "Creates a commit directly on the specified branch."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "File path in the repository.",
                },
                "content": {
                    "type": "STRING",
                    "description": "New file content (full file, not a patch).",
                },
                "message": {
                    "type": "STRING",
                    "description": "Git commit message (Japanese preferred).",
                },
                "branch": {
                    "type": "STRING",
                    "description": "Target branch. Default: repo default branch.",
                },
            },
            "required": ["path", "content", "message"],
        },
    },
    {
        "name": "create_pull_request",
        "description": "Create a pull request on GitHub.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {
                    "type": "STRING",
                    "description": "PR title.",
                },
                "body": {
                    "type": "STRING",
                    "description": "PR description (supports markdown).",
                },
                "head": {
                    "type": "STRING",
                    "description": "Source branch name.",
                },
                "base": {
                    "type": "STRING",
                    "description": "Target branch (default: main).",
                },
            },
            "required": ["title", "body", "head"],
        },
    },
    {
        "name": "trigger_cloud_build",
        "description": (
            "Trigger a Cloud Build to rebuild and deploy a container. "
            "Default config: 'cloudbuild-agent.yaml' (agent). "
            "Use 'cloudbuild.yaml' for the pipeline container."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "config_file": {
                    "type": "STRING",
                    "description": (
                        "Cloud Build config file path. "
                        "Options: 'cloudbuild-agent.yaml' (agent), "
                        "'cloudbuild.yaml' (pipeline)."
                    ),
                },
            },
        },
    },
    {
        "name": "register_schedule",
        "description": (
            "Create or update a Cloud Scheduler job. "
            "Schedule can be a cron expression or natural language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "job_name": {
                    "type": "STRING",
                    "description": "Scheduler job name.",
                },
                "schedule": {
                    "type": "STRING",
                    "description": "Cron expression or natural language (e.g. '0 9 * * *', '毎朝9時').",
                },
                "target_job_id": {
                    "type": "STRING",
                    "description": "Cloud Run Job ID to trigger.",
                },
                "description": {
                    "type": "STRING",
                    "description": "Optional description of the schedule.",
                },
            },
            "required": ["job_name", "schedule", "target_job_id"],
        },
    },
    {
        "name": "list_schedules",
        "description": "List all Cloud Scheduler jobs. Alias for list_scheduler_jobs.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        },
    },
    {
        "name": "delete_schedule",
        "description": "Delete a Cloud Scheduler job by name.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "job_name": {
                    "type": "STRING",
                    "description": "Short name of the scheduler job to delete.",
                },
            },
            "required": ["job_name"],
        },
    },
]


def get_gemini_tools() -> list:
    """Convert raw definitions to Gemini protos.Tool format."""
    func_declarations = []
    for defn in _RAW_DEFINITIONS:
        func_declarations.append(
            genai.protos.FunctionDeclaration(
                name=defn["name"],
                description=defn["description"],
                parameters=defn.get("parameters"),
            )
        )
    return [genai.protos.Tool(function_declarations=func_declarations)]


# Keep raw names for dispatch validation
TOOL_NAMES = {d["name"] for d in _RAW_DEFINITIONS}
