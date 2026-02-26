"""
Agent Orchestrator — autonomous pipeline management agent.

Phase 1: Tool dispatch framework with --test-tools mode.
Phase 2: Gemini Function Calling loop for autonomous operation.
Phase 3: Snapshot-based diff verification with --run-with-verification.

Usage:
    python -m agent.orchestrator --test-tools                # Phase 1 QA
    python -m agent.orchestrator                             # Run agent (default: health check)
    python -m agent.orchestrator --task "check errors"       # Custom task
    python -m agent.orchestrator --max-turns 5               # Limit conversation turns
    python -m agent.orchestrator --run-with-verification     # Run pipeline + verify diff
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback

import google.generativeai as genai

from agent.config import GEMINI_API_KEY, GEMINI_MODEL, get_logger
from agent.system_prompt import SYSTEM_PROMPT
from agent.tool_definitions import get_gemini_tools, TOOL_NAMES
from agent.notifier import notify
from agent.tools.logs_reader import read_logs
from agent.tools.scheduler_client import (
    list_jobs,
    pause_job,
    resume_job,
    trigger_job,
)
from agent.tools.sheets_reader import read_sheet, list_sheets
from agent.tools.job_runner import run_job, get_execution_status
from agent.tools.github_client import (
    get_file as github_get_file,
    update_file as github_update_file,
    create_pull_request,
)
from agent.tools.scheduler_manager import (
    register as register_schedule,
    delete_schedule,
)
from agent.tools.cloudbuild_client import trigger_build

logger = get_logger("agent.orchestrator")

# ── Tool dispatch map ──
# Maps tool name → callable function
TOOL_DISPATCH = {
    # Existing tools
    "read_logs": read_logs,
    "list_scheduler_jobs": list_jobs,
    "pause_scheduler_job": pause_job,
    "resume_scheduler_job": resume_job,
    "trigger_scheduler_job": trigger_job,
    "read_sheet": read_sheet,
    "list_sheets": list_sheets,
    "run_pipeline_job": run_job,
    "get_execution_status": get_execution_status,
    # GitHub tools
    "get_github_file": github_get_file,
    "update_github_file": github_update_file,
    "create_pull_request": create_pull_request,
    # Cloud Build tool
    "trigger_cloud_build": trigger_build,
    # Scheduler management tools
    "register_schedule": register_schedule,
    "list_schedules": list_jobs,       # alias — same underlying function
    "delete_schedule": delete_schedule,
}

DEFAULT_TASK = (
    "パイプラインの健全性チェックを実行してください。\n"
    "1. 直近24時間のエラーログを確認\n"
    "2. スケジューラジョブの状態を確認\n"
    "3. settingsシートとpipeline_statusシートを確認\n"
    "4. 問題があれば報告、なければ正常を報告"
)


def dispatch_tool(tool_name: str, tool_input: dict) -> str:
    """
    Dispatch a tool call and return the result as a JSON string.

    Args:
        tool_name: Name of the tool to call (must be in TOOL_DISPATCH).
        tool_input: Dict of arguments to pass to the tool function.

    Returns:
        JSON string of the tool result.

    Raises:
        ValueError: If the tool name is unknown.
    """
    if tool_name not in TOOL_DISPATCH:
        raise ValueError(
            f"Unknown tool: {tool_name}. "
            f"Available: {list(TOOL_DISPATCH.keys())}"
        )

    func = TOOL_DISPATCH[tool_name]
    logger.info("Dispatching tool: %s(%s)", tool_name, tool_input)

    result = func(**tool_input)
    return json.dumps(result, ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════════════════
# Phase 2: Gemini Function Calling loop
# ═══════════════════════════════════════════════════════════

# Module-level model instance (lazy init)
_gemini_model = None


def _get_model():
    """Lazy-init Gemini model with tools and system instruction."""
    global _gemini_model
    if _gemini_model is None:
        genai.configure(api_key=GEMINI_API_KEY)
        _gemini_model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            tools=get_gemini_tools(),
            system_instruction=SYSTEM_PROMPT,
            generation_config=genai.GenerationConfig(
                max_output_tokens=4096,
                temperature=0.7,
            ),
        )
    return _gemini_model


def run_agent(task: str = DEFAULT_TASK, max_turns: int = 15) -> tuple[str, int, int]:
    """
    Run the autonomous agent with a Gemini Function Calling loop.

    Args:
        task: The task/instruction for the agent to execute.
        max_turns: Maximum number of API round-trips (safety limit).

    Returns:
        Tuple of (final_response, turns_used, tool_calls_count).
    """
    model = _get_model()
    chat = model.start_chat()

    final_response = ""
    turn = 0
    total_tool_calls = 0

    logger.info("Starting agent loop (max_turns=%d, model=%s)", max_turns, GEMINI_MODEL)
    logger.info("Task: %s", task[:200])

    # Send initial message
    try:
        response = chat.send_message(task)
    except Exception as e:
        logger.error("Gemini API error on initial message: %s", e)
        notify("Agent API Error", f"Gemini API call failed:\n```\n{e}\n```", is_error=True)
        return (f"API Error: {e}", 1, 0)

    while turn < max_turns:
        turn += 1
        logger.info("── Turn %d/%d ──", turn, max_turns)

        # Extract function calls and text from response parts
        function_calls = []
        text_parts = []

        try:
            parts = response.candidates[0].content.parts
        except (IndexError, AttributeError):
            final_response = "Agent returned empty response."
            logger.warning("Empty response at turn %d", turn)
            break

        for part in parts:
            if part.function_call.name:
                function_calls.append(part.function_call)
            if part.text:
                text_parts.append(part.text)
                logger.info("Agent text: %s", part.text[:200])

        # If no function calls, agent is done (text-only response)
        if not function_calls:
            final_response = "\n".join(text_parts) if text_parts else "Agent ended without response."
            logger.info("Agent completed at turn %d", turn)
            break

        # Execute all function calls and collect responses
        function_responses = []
        for fc in function_calls:
            tool_name = fc.name
            tool_input = dict(fc.args) if fc.args else {}

            total_tool_calls += 1
            logger.info("Tool call: %s(%s)", tool_name, json.dumps(tool_input, ensure_ascii=False)[:200])

            try:
                result_json = dispatch_tool(tool_name, tool_input)
                result_dict = json.loads(result_json)
                logger.info("Tool result: %s", result_json[:200])
            except Exception as e:
                result_dict = {"error": str(e)}
                logger.error("Tool dispatch failed: %s", e)

            function_responses.append(
                genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=tool_name,
                        response={"result": result_dict},
                    )
                )
            )

        # Send function responses back to the model
        try:
            response = chat.send_message(function_responses)
        except Exception as e:
            logger.error("Gemini API error on function response: %s", e)
            notify("Agent API Error", f"Gemini API call failed:\n```\n{e}\n```", is_error=True)
            return (f"API Error: {e}", turn, total_tool_calls)

    else:
        # max_turns exceeded
        final_response = f"Agent reached max_turns limit ({max_turns})."
        logger.warning("Max turns (%d) exceeded", max_turns)

    return final_response, turn, total_tool_calls


# ═══════════════════════════════════════════════════════════
# Phase 1: test tools
# ═══════════════════════════════════════════════════════════


def test_tools() -> bool:
    """
    Validate all tools can be imported and dispatched.
    Calls each tool with safe/minimal arguments.
    Returns True if all tests pass.
    """
    print("=" * 60)
    print("Agent Tool Test Suite — Phase 1")
    print("=" * 60)

    results = {}

    # ── 1. read_logs ──
    _run_test(
        results,
        "read_logs",
        {"job_name": "marketprobe-pipeline", "severity": "ERROR", "minutes": 5, "limit": 3},
    )

    # ── 2. list_scheduler_jobs ──
    _run_test(results, "list_scheduler_jobs", {})

    # ── 3. read_sheet (settings) ──
    _run_test(results, "read_sheet", {"sheet_name": "settings", "row_limit": 5})

    # ── 4. list_sheets ──
    _run_test(results, "list_sheets", {})

    # ── 5. Verify tool definitions match dispatch ──
    print(f"\n{'─' * 40}")
    print("Checking tool_definitions ↔ dispatch consistency...")
    definition_names = TOOL_NAMES
    dispatch_names = set(TOOL_DISPATCH.keys())
    missing_dispatch = definition_names - dispatch_names
    missing_defs = dispatch_names - definition_names
    if missing_dispatch:
        print(f"  ❌ Defined but no dispatch: {missing_dispatch}")
        results["consistency"] = False
    elif missing_defs:
        print(f"  ❌ Dispatch but no definition: {missing_defs}")
        results["consistency"] = False
    else:
        print(f"  ✅ All {len(definition_names)} tools have matching definitions and dispatch")
        results["consistency"] = True

    # ── Summary ──
    print(f"\n{'=' * 60}")
    print("Test Results:")
    all_passed = True
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {name}")
        if not passed:
            all_passed = False

    print(f"\n{'=' * 60}")
    if all_passed:
        print("🎉 All tests passed! Phase 1 tools are operational.")
    else:
        print("⚠️  Some tests failed. Check errors above.")
    print(f"{'=' * 60}")

    return all_passed


def _run_test(results: dict, tool_name: str, tool_input: dict) -> None:
    """Run a single tool test and record the result."""
    print(f"\n{'─' * 40}")
    print(f"Testing: {tool_name}({json.dumps(tool_input, ensure_ascii=False)})")
    try:
        result_json = dispatch_tool(tool_name, tool_input)
        result = json.loads(result_json)

        # Show a brief preview of the result
        if isinstance(result, list):
            print(f"  ✅ Returned {len(result)} items")
            if result:
                # Show first item keys
                if isinstance(result[0], dict):
                    print(f"     Keys: {list(result[0].keys())}")
                else:
                    print(f"     First: {str(result[0])[:80]}")
        elif isinstance(result, dict):
            print(f"  ✅ Returned dict with keys: {list(result.keys())}")
        else:
            print(f"  ✅ Returned: {str(result)[:100]}")

        results[tool_name] = True

    except Exception as e:
        print(f"  ❌ Error: {e}")
        traceback.print_exc()
        results[tool_name] = False


def wait_for_completion(execution_name: str, timeout: int = 2400, interval: int = 30) -> str:
    """
    Wait for a Cloud Run Job execution to complete.

    Polls get_execution_status() every `interval` seconds until
    the execution succeeds, fails, or times out.

    Args:
        execution_name: Full resource name of the execution (from run_job).
        timeout: Maximum wait time in seconds (default: 2400 = 40 min).
        interval: Polling interval in seconds (default: 30).

    Returns:
        Final status string ('succeeded' or 'failed').

    Raises:
        RuntimeError: If the execution fails.
        TimeoutError: If timeout is exceeded.
    """
    start = time.time()
    logger.info("Waiting for execution: %s (timeout=%ds)", execution_name, timeout)

    while time.time() - start < timeout:
        status_info = get_execution_status(execution_name)
        status = status_info.get("status", "unknown")

        elapsed = int(time.time() - start)
        logger.info("Execution status: %s (elapsed=%ds)", status, elapsed)

        if status == "succeeded":
            return status
        if status == "failed":
            raise RuntimeError(f"ジョブ失敗: execution={execution_name}")

        time.sleep(interval)

    raise TimeoutError(f"{timeout}秒以内に完了しませんでした: {execution_name}")


def run_with_verification() -> bool:
    """
    Run orchestrate_v2 with before/after snapshot verification.

    Flow:
      1. Save before-snapshot
      2. Start orchestrate_v2 via Cloud Run
      3. Wait for completion (max 40 min)
      4. Take after-snapshot and compute diff score
      5. Generate agent commentary on results
      6. Notify and record to history

    Returns:
        True if consistency score >= 60.
    """
    from agent.verification.consistency_checker import save_snapshot, check_with_snapshot
    from agent.learning.history_writer import record_run

    start_time = time.time()

    # Step 1: Before snapshot
    logger.info("=" * 60)
    logger.info("run-with-verification: Step 1 — Before snapshot")
    logger.info("=" * 60)
    before_path = save_snapshot()
    notify("📸 実行前スナップショット取得完了", f"保存先: {before_path}")

    # Step 2: Start orchestrate_v2
    logger.info("=" * 60)
    logger.info("run-with-verification: Step 2 — Starting orchestrate_v2")
    logger.info("=" * 60)
    run_result = run_job("orchestrate_v2")
    execution_name = run_result.get("execution_name", "")
    notify(
        "🔬 orchestrate_v2 起動",
        f"execution: {execution_name}\njob: {run_result.get('job_name', '')}",
    )

    # Step 3: Wait for completion
    logger.info("=" * 60)
    logger.info("run-with-verification: Step 3 — Waiting for completion")
    logger.info("=" * 60)
    try:
        final_status = wait_for_completion(execution_name, timeout=2400, interval=30)
        logger.info("Job completed: status=%s", final_status)
    except (RuntimeError, TimeoutError) as e:
        elapsed = time.time() - start_time
        error_msg = str(e)
        logger.error("Job failed or timed out: %s", error_msg)
        notify(f"❌ orchestrate_v2 失敗 ({elapsed:.0f}秒)", error_msg, is_error=True)
        record_run(
            task="run-with-verification",
            duration_seconds=elapsed,
            turns_used=0,
            tool_calls_count=0,
            consistency_score=0,
            errors=[error_msg],
            response_summary=f"ジョブ失敗: {error_msg}",
        )
        return False

    # Step 4: After snapshot + diff check
    logger.info("=" * 60)
    logger.info("run-with-verification: Step 4 — Consistency check")
    logger.info("=" * 60)
    check_result = check_with_snapshot(before_path)

    print("\n" + "=" * 60)
    print("整合性チェック結果:")
    print("=" * 60)
    print(check_result.summary())

    # Step 5: Agent commentary
    logger.info("=" * 60)
    logger.info("run-with-verification: Step 5 — Agent commentary")
    logger.info("=" * 60)
    commentary, turns, tool_calls = run_agent(
        task=(
            f"以下の整合性チェック結果を分析し、問題点と推奨アクションをまとめてください。\n\n"
            f"スコア: {check_result.score}/100\n"
            f"内訳: {json.dumps(check_result.breakdown, ensure_ascii=False)}\n"
            f"差分: {json.dumps(check_result.diff, ensure_ascii=False)}\n"
            f"エラー: {json.dumps(check_result.errors, ensure_ascii=False)}"
        ),
        max_turns=3,
    )

    # Step 6: Notify + record
    elapsed = time.time() - start_time
    score_report = (
        f"📊 整合性スコア: {check_result.score}/100\n\n"
        f"{check_result.summary()}\n\n"
        f"---\n{commentary[:1500]}"
    )

    notify(
        f"整合性レポート (スコア: {check_result.score}/100, {elapsed:.0f}秒)",
        score_report,
        is_error=not check_result.is_healthy,
    )

    record_run(
        task="run-with-verification",
        duration_seconds=elapsed,
        turns_used=turns,
        tool_calls_count=tool_calls,
        consistency_score=check_result.score,
        errors=check_result.errors,
        response_summary=commentary[:500],
    )

    logger.info("=" * 60)
    logger.info("run-with-verification completed: score=%d, elapsed=%.0fs", check_result.score, elapsed)
    logger.info("=" * 60)

    return check_result.is_healthy


def main():
    parser = argparse.ArgumentParser(description="MarketProbe Agent Orchestrator")
    parser.add_argument(
        "--test-tools",
        action="store_true",
        help="Run tool validation tests (Phase 1 QA)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="(Deprecated) Use --run-with-verification instead",
    )
    parser.add_argument(
        "--run-with-verification",
        action="store_true",
        help="Run orchestrate_v2 with before/after snapshot verification",
    )
    parser.add_argument(
        "--task",
        type=str,
        default="",
        help="Custom task for the agent (default: health check)",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=15,
        help="Maximum number of API round-trips (default: 15)",
    )
    args = parser.parse_args()

    if args.test_tools:
        success = test_tools()
        sys.exit(0 if success else 1)

    if args.verify:
        print("⚠️  --verify 単体は廃止されました。")
        print("   正確な差分検証には --run-with-verification を使用してください。")
        sys.exit(1)

    if args.run_with_verification:
        healthy = run_with_verification()
        sys.exit(0 if healthy else 1)

    # Run the agent — priority: AGENT_TASK env > --task arg > DEFAULT_TASK
    agent_task_env = os.environ.get("AGENT_TASK", "")
    agent_context_env = os.environ.get("AGENT_CONTEXT", "")

    if agent_task_env:
        from agent.task_router import route_task
        task, max_turns = route_task(agent_task_env, agent_context_env)
        # Allow explicit --max-turns to override router's suggestion
        if args.max_turns != 15:
            max_turns = args.max_turns
        logger.info("AGENT_TASK from env: %s", agent_task_env[:200])
    elif args.task:
        task = args.task
        max_turns = args.max_turns
    else:
        task = DEFAULT_TASK
        max_turns = args.max_turns

    start_time = time.time()

    logger.info("=" * 60)
    logger.info("MarketProbe Agent — Starting")
    logger.info("=" * 60)

    result, turns_used, tool_calls_count = run_agent(task=task, max_turns=max_turns)

    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("Agent completed in %.1f seconds (%d turns, %d tool calls)", elapsed, turns_used, tool_calls_count)
    logger.info("=" * 60)

    # Print the final response
    print("\n" + "=" * 60)
    print("Agent Response:")
    print("=" * 60)
    print(result)

    # Send notification
    is_error = "error" in result.lower() or "失敗" in result
    notify(
        f"パイプライン巡回完了 ({elapsed:.0f}秒, {turns_used}ターン)",
        result[:2000],
        is_error=is_error,
    )

    # Phase 4: Record to history and detect patterns
    try:
        from agent.learning.history_writer import record_run
        from agent.learning.pattern_detector import detect_patterns, generate_direction_update

        # Record this run
        run_errors = []
        if is_error:
            run_errors.append("Agent response indicates error")

        record_run(
            task=task,
            duration_seconds=elapsed,
            turns_used=turns_used,
            tool_calls_count=tool_calls_count,
            consistency_score=None,  # Only set when --verify is used
            errors=run_errors,
            response_summary=result[:500],
        )
        logger.info("Run recorded to agent_history")

        # Detect patterns
        patterns_result = detect_patterns()
        if patterns_result.get("recommendations"):
            direction_update = generate_direction_update(patterns_result)
            if direction_update:
                logger.info("Pattern detection recommendations:\n%s", direction_update)
                print("\n" + "─" * 40)
                print("Learning Loop — Pattern Detection:")
                print("─" * 40)
                print(direction_update)

    except Exception as e:
        logger.warning("Learning loop failed (non-critical): %s", e)


if __name__ == "__main__":
    main()
