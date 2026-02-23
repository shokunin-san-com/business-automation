"""
Claude API tool_use definitions — JSON schemas for the agent tools.

Each tool definition follows the Anthropic tool_use format:
  { "name": str, "description": str, "input_schema": JSON Schema }
"""

TOOL_DEFINITIONS = [
    {
        "name": "read_logs",
        "description": (
            "Read Cloud Run Job logs from Cloud Logging. "
            "Use this to check for errors, warnings, or recent execution results "
            "from any pipeline job."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_name": {
                    "type": "string",
                    "description": (
                        "Cloud Run job name to filter logs. "
                        "Default: 'marketprobe-pipeline'. "
                        "Empty string returns logs from all jobs."
                    ),
                },
                "severity": {
                    "type": "string",
                    "enum": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                    "description": "Minimum log severity to fetch. Default: 'ERROR'.",
                },
                "minutes": {
                    "type": "integer",
                    "description": "How many minutes back to look. Default: 60.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of log entries. Default: 50.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "list_scheduler_jobs",
        "description": (
            "List all Cloud Scheduler jobs with their schedule, state (ENABLED/PAUSED), "
            "and description. Use this to understand the current cron schedule."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "pause_scheduler_job",
        "description": (
            "Pause a Cloud Scheduler job so it stops executing on its cron schedule. "
            "The job can be resumed later."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_name": {
                    "type": "string",
                    "description": "Short name of the scheduler job to pause.",
                },
            },
            "required": ["job_name"],
        },
    },
    {
        "name": "resume_scheduler_job",
        "description": "Resume a previously paused Cloud Scheduler job.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_name": {
                    "type": "string",
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
        "input_schema": {
            "type": "object",
            "properties": {
                "job_name": {
                    "type": "string",
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
            "Available sheets include: settings, market_research, market_selection, "
            "competitor_analysis, business_ideas, knowledge_base, and more."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet_name": {
                    "type": "string",
                    "description": (
                        "Name of the worksheet tab to read "
                        "(e.g. 'settings', 'market_research', 'business_ideas')."
                    ),
                },
                "row_limit": {
                    "type": "integer",
                    "description": "Maximum number of rows to return. Default: 100.",
                },
            },
            "required": ["sheet_name"],
        },
    },
    {
        "name": "list_sheets",
        "description": "List all worksheet tab names in the pipeline spreadsheet.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "run_pipeline_job",
        "description": (
            "Start a Cloud Run Job execution for a specific pipeline script. "
            "Each script has its own Cloud Run Job. "
            "Available scripts and their jobs: "
            "A_market_research (market-research), "
            "B_market_selection (market-selection), "
            "C_competitor_analysis (competitor-analysis), "
            "0_idea_generator (idea-generator), "
            "1_lp_generator (lp-generator), "
            "2_sns_poster (sns-poster), "
            "3_form_sales (form-sales), "
            "4_analytics_reporter (analytics-reporter), "
            "5_slack_reporter (slack-reporter), "
            "6_ads_monitor (ads-monitor), "
            "7_learning_engine (learning-engine). "
            "Scripts without a dedicated job (e.g. orchestrate_abc0) "
            "run via market-research with a SCRIPT_NAME override."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "script_name": {
                    "type": "string",
                    "description": (
                        "Script key from the pipeline dispatcher. "
                        "Examples: 'A_market_research', 'B_market_selection', "
                        "'0_idea_generator', 'orchestrate_abc0'."
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
        "input_schema": {
            "type": "object",
            "properties": {
                "execution_name": {
                    "type": "string",
                    "description": "Full resource name of the execution to check.",
                },
            },
            "required": ["execution_name"],
        },
    },
    # ── GitHub tools ─────────────────────────────────────────────
    {
        "name": "get_github_file",
        "description": (
            "Get the contents of a file from the GitHub repository. "
            "Returns the file content (decoded text), SHA, and path. "
            "Use this to read source code, configs, or any file in the repo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "File path in the repository "
                        "(e.g. 'agent/config.py', 'run.py', 'scripts/A_market_research.py')."
                    ),
                },
                "ref": {
                    "type": "string",
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
            "Creates a commit directly on the specified branch. "
            "Use this for small fixes, config changes, or creating new files. "
            "Always work on a feature branch and create a PR — avoid committing "
            "directly to main."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path in the repository.",
                },
                "content": {
                    "type": "string",
                    "description": "New file content (full file, not a patch).",
                },
                "message": {
                    "type": "string",
                    "description": "Git commit message (Japanese preferred).",
                },
                "branch": {
                    "type": "string",
                    "description": "Target branch. Default: repo default branch.",
                },
            },
            "required": ["path", "content", "message"],
        },
    },
    {
        "name": "create_pull_request",
        "description": (
            "Create a pull request on GitHub. "
            "Use after updating files on a feature branch."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "PR title.",
                },
                "body": {
                    "type": "string",
                    "description": "PR description (supports markdown).",
                },
                "head": {
                    "type": "string",
                    "description": "Source branch name.",
                },
                "base": {
                    "type": "string",
                    "description": "Target branch (default: main).",
                },
            },
            "required": ["title", "body", "head"],
        },
    },
    # ── Cloud Build tool ─────────────────────────────────────────
    {
        "name": "trigger_cloud_build",
        "description": (
            "Trigger a Cloud Build to rebuild and deploy a container. "
            "Default config: 'cloudbuild-agent.yaml' (builds the agent container). "
            "Use 'cloudbuild.yaml' for the pipeline container. "
            "Use after code changes to redeploy."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "config_file": {
                    "type": "string",
                    "description": (
                        "Cloud Build config file path. "
                        "Options: 'cloudbuild-agent.yaml' (agent), "
                        "'cloudbuild.yaml' (pipeline). "
                        "Default: 'cloudbuild-agent.yaml'."
                    ),
                },
            },
            "required": [],
        },
    },
    # ── Scheduler management tools ───────────────────────────────
    {
        "name": "register_schedule",
        "description": (
            "Create or update a Cloud Scheduler job. "
            "Schedule can be a cron expression or natural language: "
            "'毎朝9時', '毎日14:30', '毎週月曜9時', 'every 3 hours', "
            "'0 9 * * *'. "
            "The scheduler triggers a Cloud Run Job at the specified schedule."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_name": {
                    "type": "string",
                    "description": (
                        "Scheduler job name (e.g. 'schedule-v2-morning', "
                        "'schedule-lp-daily')."
                    ),
                },
                "schedule": {
                    "type": "string",
                    "description": (
                        "Cron expression or natural language. "
                        "Examples: '0 9 * * *', '毎朝9時', '毎日14:30', "
                        "'every 3 hours'."
                    ),
                },
                "target_job_id": {
                    "type": "string",
                    "description": (
                        "Cloud Run Job ID to trigger. "
                        "Examples: 'market-research', 'lp-generator', "
                        "'agent-orchestrator', 'orchestrate-v2'."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "Optional description of the schedule.",
                },
            },
            "required": ["job_name", "schedule", "target_job_id"],
        },
    },
    {
        "name": "list_schedules",
        "description": (
            "List all Cloud Scheduler jobs with their schedule, state, "
            "and description. Same as list_scheduler_jobs — provided as "
            "a convenient alias for scheduling workflows."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "delete_schedule",
        "description": "Delete a Cloud Scheduler job by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_name": {
                    "type": "string",
                    "description": "Short name of the scheduler job to delete.",
                },
            },
            "required": ["job_name"],
        },
    },
]
