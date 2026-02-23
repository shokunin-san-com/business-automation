"""
Task Router — pre-processes AGENT_TASK into an optimised prompt.

When the agent is launched from the chat bridge (/api/agent/execute),
the AGENT_TASK and AGENT_CONTEXT environment variables carry the user's
instruction and metadata.  This module:

1. Classifies the task into a category (schedule_register, code_fix, …).
2. Prepends a role-appropriate preamble so Claude picks the right tools.
3. Returns the combined prompt and a task-specific max_turns limit.
"""

from __future__ import annotations

import json
import re

from agent.config import get_logger

logger = get_logger(__name__)


# ── Task classification patterns ─────────────────────────────────

TASK_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("schedule_register", re.compile(
        r"スケジュール|スケジューラ|cron|定期|schedule|毎朝|毎日|毎週|予約|登録.*時",
        re.IGNORECASE,
    )),
    ("code_fix", re.compile(
        r"修正|バグ|fix|bug|エラー修正|コード.*変更|update.*code|直して",
        re.IGNORECASE,
    )),
    ("code_read", re.compile(
        r"コード.*読|ソース.*確認|ファイル.*見|read.*code|確認して.*コード|コード.*確認",
        re.IGNORECASE,
    )),
    ("health_check", re.compile(
        r"健全性|ヘルスチェック|health|エラー確認|ログ確認|状態確認|巡回|診断",
        re.IGNORECASE,
    )),
    ("pipeline_execute", re.compile(
        r"実行|走らせ|run|execute|パイプライン.*開始|起動",
        re.IGNORECASE,
    )),
]

# Sensible turn limits per task type
MAX_TURNS_MAP: dict[str, int] = {
    "schedule_register": 5,
    "code_fix": 15,
    "code_read": 5,
    "health_check": 10,
    "pipeline_execute": 8,
    "general": 15,
}

# Step-by-step preambles injected before the user's instruction
TASK_PREAMBLES: dict[str, str] = {
    "schedule_register": (
        "以下のスケジュール登録タスクを実行してください。\n"
        "1. list_schedules で現在のスケジューラ一覧を確認\n"
        "2. register_schedule で新規登録または更新\n"
        "3. 登録結果を報告\n\n"
        "ユーザーの指示:\n"
    ),
    "code_fix": (
        "以下のコード修正タスクを実行してください。\n"
        "1. get_github_file で現在のコードを確認\n"
        "2. 問題を特定\n"
        "3. update_github_file で修正（feature ブランチに）\n"
        "4. create_pull_request でPRを作成\n"
        "5. 必要に応じて trigger_cloud_build でビルド確認\n\n"
        "ユーザーの指示:\n"
    ),
    "code_read": (
        "以下のコード確認タスクを実行してください。\n"
        "get_github_file でファイルを読み、内容を要約して報告してください。\n\n"
        "ユーザーの指示:\n"
    ),
    "health_check": (
        "パイプラインの健全性チェックを実行してください。\n"
        "1. 直近24時間のエラーログを確認\n"
        "2. スケジューラジョブの状態を確認\n"
        "3. settingsシートとpipeline_statusシートを確認\n"
        "4. 問題があれば報告、なければ正常を報告\n\n"
        "追加の指示:\n"
    ),
    "pipeline_execute": (
        "以下のパイプライン実行タスクを実行してください。\n"
        "1. 指定されたジョブを run_pipeline_job で実行\n"
        "2. get_execution_status で完了を確認\n"
        "3. read_logs で実行結果を確認\n"
        "4. 結果を報告\n\n"
        "ユーザーの指示:\n"
    ),
}


# ── Public API ───────────────────────────────────────────────────


def classify_task(task: str) -> str:
    """Classify a task string into a task type.

    Returns one of: schedule_register, code_fix, code_read,
    health_check, pipeline_execute, general.
    """
    for task_type, pattern in TASK_PATTERNS:
        if pattern.search(task):
            return task_type
    return "general"


def route_task(task: str, context_json: str = "") -> tuple[str, int]:
    """Route a task to the appropriate execution strategy.

    Args:
        task:         The AGENT_TASK string from the environment variable.
        context_json: Optional AGENT_CONTEXT JSON string.

    Returns:
        Tuple of (optimised_task_prompt, max_turns).
    """
    task_type = classify_task(task)
    max_turns = MAX_TURNS_MAP.get(task_type, 15)

    logger.info("Task classified as '%s' (max_turns=%d)", task_type, max_turns)

    # Build optimised prompt
    preamble = TASK_PREAMBLES.get(task_type, "")

    # Parse context if provided
    context_str = ""
    if context_json:
        try:
            context = json.loads(context_json)
            parts: list[str] = []
            if context.get("triggered_by"):
                parts.append(f"指示者: {context['triggered_by']}")
            if context.get("source"):
                parts.append(f"ソース: {context['source']}")
            if context.get("thread_id"):
                parts.append(f"スレッド: {context['thread_id']}")
            if parts:
                context_str = "\nコンテキスト: " + " / ".join(parts) + "\n"
        except json.JSONDecodeError:
            logger.warning("Failed to parse AGENT_CONTEXT: %s", context_json[:100])

    optimised_task = f"{preamble}{context_str}{task}"

    return optimised_task, max_turns
