"""
orchestrate_v2.py — V2 Evidence-gate pipeline orchestrator.

Flow: A0 → A1q → A1d → EX → C(20) → 0(3offers) → LP-guard → Notify.

All scoring is **prohibited**. Decisions are PASS/FAIL based on evidence URLs.
run_id is generated once and propagated to all steps for traceability.

Continuous mode: settings シートの v2_continuous_mode=true で連続実行。
完了後に Cloud Run Job を自動再トリガーする（最大10回連続、エラー時停止）。

Usage:
    SCRIPT_NAME=orchestrate_v2 python run.py
    python scripts/orchestrate_v2.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_DIR, GCP_PROJECT_ID, get_logger
from utils.sheets_client import (
    get_all_rows, append_rows, get_sheet_urls,
    get_setting, find_row_index, update_cell,
)
from utils.slack_notifier import send_message as notify
from utils.status_writer import update_status

GCP_REGION = os.getenv("GCP_REGION", "asia-northeast1")
CONTINUOUS_MAX_RUNS = 10
CONTINUOUS_COOLDOWN_SEC = 60  # 再トリガー前の待機時間

# Import V2 step modules
from A_market_research import (
    step_a0_generate_micro_markets,
    step_a1_quick_gate,
    step_a1_deep_gate,
    check_exploration_lane,
    save_settings_snapshot,
)
from C_competitor_analysis import analyze_competitors_20, save_competitors_to_sheets
from utils.pdf_knowledge import get_knowledge_summary

logger = get_logger("orchestrate_v2", "orchestrate_v2.log")

# Step result constants
STEP_OK = "✅ 成功"
STEP_WARN = "⚠️ 警告あり"
STEP_FAIL = "❌ 失敗"
STEP_SKIP = "⏭️ スキップ"

# Sheet names for each step (for report links)
STEP_SHEET_MAP = {
    "A0": ["micro_market_list"],
    "A1q": ["micro_market_list"],
    "A1d": ["gate_decision_log"],
    "EX": ["exploration_lane_log"],
    "C": ["competitor_20_log"],
    "0": ["offer_3_log"],
    "LP": ["lp_ready_log"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_settings() -> dict:
    rows = get_all_rows("settings")
    return {r["key"]: r["value"] for r in rows}


def _make_step_result(
    name: str,
    status: str,
    count: int = 0,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
    data: object = None,
) -> dict:
    return {
        "name": name,
        "status": status,
        "count": count,
        "errors": errors or [],
        "warnings": warnings or [],
        "data": data,
    }


# ---------------------------------------------------------------------------
# LP readiness check (local — no API call, direct Sheets check)
# ---------------------------------------------------------------------------

def check_lp_ready(run_id: str) -> dict:
    """Check if all conditions for LP creation are met.

    Conditions:
    1. gate_decision_log has PASS for this run_id
       (exploration_lane ACTIVE is NOT sufficient — evidence gate must pass)
    2. competitor_20_log has records for this run_id
    3. offer_3_log has 3 complete records for this run_id

    Returns dict with status (READY/BLOCKED) and missing items.
    """
    missing = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 1. Gate check — A1d PASS required (exploration lane alone is not enough)
    gate_ok = False
    is_exploration_only = False
    try:
        gate_rows = get_all_rows("gate_decision_log")
        gate_pass = [r for r in gate_rows if r.get("run_id") == run_id and r.get("status") == "PASS"]
        if gate_pass:
            gate_ok = True
        else:
            # Check if running via exploration lane
            lane_rows = get_all_rows("exploration_lane_log")
            lane_active = [r for r in lane_rows if r.get("run_id") == run_id and r.get("status") == "ACTIVE"]
            if lane_active:
                is_exploration_only = True
    except Exception:
        pass
    if not gate_ok:
        if is_exploration_only:
            missing.append("探索レーン中: A1dゲート未通過（ヒアリングで証拠収集後に再判定が必要）")
        else:
            missing.append("gate_decision_log: PASSレコードなし")

    # 2. Competitor check
    competitor_ok = False
    try:
        comp_rows = get_all_rows("competitor_20_log")
        comp_for_run = [r for r in comp_rows if r.get("run_id") == run_id]
        if len(comp_for_run) >= 10:  # At least 10 companies
            competitor_ok = True
        else:
            missing.append(f"competitor_20_log: {len(comp_for_run)}社のみ（10社以上必要）")
    except Exception:
        missing.append("competitor_20_log: データ取得エラー")

    # 3. Offer check
    offer_ok = False
    try:
        offer_rows = get_all_rows("offer_3_log")
        offers_for_run = [r for r in offer_rows if r.get("run_id") == run_id]
        if len(offers_for_run) >= 3:
            # Check all 7 required fields are non-empty
            required = ["payer", "offer_name", "deliverable", "time_to_value", "price", "replaces", "upsell"]
            complete = all(
                all(str(o.get(f, "")).strip() for f in required)
                for o in offers_for_run[:3]
            )
            if complete:
                offer_ok = True
            else:
                missing.append("offer_3_log: 必須フィールドに空欄あり")
        else:
            missing.append(f"offer_3_log: {len(offers_for_run)}案のみ（3案必要）")
    except Exception:
        missing.append("offer_3_log: データ取得エラー")

    status = "READY" if (gate_ok and competitor_ok and offer_ok) else "BLOCKED"
    blocked_reason = " / ".join(missing) if missing else ""

    # Save to lp_ready_log
    try:
        append_rows("lp_ready_log", [[
            run_id,
            now,
            str(gate_ok),
            str(competitor_ok),
            str(offer_ok),
            status,
            blocked_reason,
        ]])
    except Exception as e:
        logger.warning(f"Failed to write lp_ready_log: {e}")

    return {
        "status": status,
        "gate_ok": gate_ok,
        "competitor_ok": competitor_ok,
        "offer_ok": offer_ok,
        "is_exploration_only": is_exploration_only,
        "missing": missing,
    }


# ---------------------------------------------------------------------------
# Pipeline report
# ---------------------------------------------------------------------------

def send_pipeline_report(
    steps: list[dict],
    run_id: str,
    lp_check: dict,
    total_duration: str,
    passed_market_count: int = 0,
    offer_count: int = 0,
):
    """Send a comprehensive pipeline report to Slack."""
    try:
        all_sheet_names = set()
        for s in steps:
            step_key = s["name"].split(":")[0]
            for sn in STEP_SHEET_MAP.get(step_key, []):
                all_sheet_names.add(sn)
        sheet_urls = get_sheet_urls(list(all_sheet_names)) if all_sheet_names else {}
    except Exception:
        sheet_urls = {}

    has_errors = any(s["status"] == STEP_FAIL for s in steps)
    has_warnings = any(s["status"] == STEP_WARN for s in steps)

    header = "🚀 *V2パイプライン完了*"
    if has_errors:
        header = "🚨 *V2パイプライン完了（エラーあり）*"
    elif has_warnings:
        header = "⚠️ *V2パイプライン完了（警告あり）*"

    lines = [
        header,
        f"⏱️ {total_duration}  |  🔑 run_id: `{run_id[:8]}`",
        "",
    ]

    # Step results
    for s in steps:
        step_key = s["name"].split(":")[0]
        relevant = STEP_SHEET_MAP.get(step_key, [])
        link_parts = [f"<{sheet_urls[sn]}|{sn}>" for sn in relevant if sn in sheet_urls]
        link_str = f"  → {' '.join(link_parts)}" if link_parts else ""
        count_str = f" ({s['count']}件)" if s.get("count") else ""
        lines.append(f"  {s['status']} {s['name']}{count_str}{link_str}")
        if s.get("errors"):
            for e in s["errors"][:3]:
                lines.append(f"    → {e}")

    # LP readiness
    lines.append("")
    lp_status = lp_check.get("status", "UNKNOWN")
    if lp_status == "READY":
        lines.append("🟢 *LP作成: READY* — 全条件クリア")
    else:
        lines.append(f"🔴 *LP作成: BLOCKED*")
        for m in lp_check.get("missing", []):
            lines.append(f"    → {m}")
        if lp_check.get("is_exploration_only"):
            lines.append("")
            lines.append("📋 *次のアクション:* 探索レーン市場のヒアリングで証拠を収集し、再度パイプラインを実行してください")

    # CEO review notification
    ceo_items = []
    if passed_market_count > 1:
        ceo_items.append(f"• PASS市場が{passed_market_count}件あります。却下して1つに絞ってください。")
    if offer_count > 1:
        ceo_items.append(f"• オファーが{offer_count}案あります。却下して絞ってください。")
    if ceo_items and lp_status == "READY":
        lines.append("")
        lines.append("👔 *CEO承認が必要です*")
        for item in ceo_items:
            lines.append(f"    {item}")
        lines.append("    → ダッシュボードから却下操作を行ってください。")

    # Spreadsheet link
    from config import GOOGLE_SHEETS_ID
    if GOOGLE_SHEETS_ID:
        ss_url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEETS_ID}/edit"
        lines.append("")
        lines.append(f"📊 <{ss_url}|スプレッドシートを開く>")

    notify("\n".join(lines))


# ---------------------------------------------------------------------------
# Abort helper
# ---------------------------------------------------------------------------

def _abort_pipeline(steps: list[dict], run_id: str, start_time: float):
    """Abort pipeline with notification."""
    elapsed = time.time() - start_time
    total_duration = f"{int(elapsed // 60)}分{int(elapsed % 60)}秒"

    lines = [
        "🚨 *V2パイプライン停止*",
        f"⏱️ {total_duration}  |  🔑 run_id: `{run_id[:8]}`",
        "",
    ]
    for s in steps:
        lines.append(f"  {s['status']} {s['name']}")
        if s.get("errors"):
            for e in s["errors"][:3]:
                lines.append(f"    → {e}")

    # Spreadsheet link
    from config import GOOGLE_SHEETS_ID
    if GOOGLE_SHEETS_ID:
        ss_url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEETS_ID}/edit"
        lines.append("")
        lines.append(f"📊 <{ss_url}|スプレッドシートを開く>")

    notify("\n".join(lines))
    update_status("orchestrate_v2", "error", f"パイプライン停止 ({total_duration})")


# ---------------------------------------------------------------------------
# Continuous mode — self re-trigger
# ---------------------------------------------------------------------------

def _get_continuous_settings() -> tuple[bool, int]:
    """Read continuous mode flag and current run count from settings sheet.

    Returns:
        (enabled, current_count)
    """
    try:
        enabled = get_setting("v2_continuous_mode", "false").lower() == "true"
        count = int(get_setting("v2_continuous_count", "0"))
        return enabled, count
    except Exception as e:
        logger.warning(f"Failed to read continuous settings: {e}")
        return False, 0


def _update_continuous_count(new_count: int) -> None:
    """Update the v2_continuous_count in settings sheet."""
    try:
        row = find_row_index("settings", "key", "v2_continuous_count")
        if row:
            # "value" is column B (index 2) in settings sheet
            update_cell("settings", row, 2, str(new_count))
        else:
            # Key doesn't exist yet — append it
            append_rows("settings", [["v2_continuous_count", str(new_count)]])
    except Exception as e:
        logger.warning(f"Failed to update continuous count: {e}")


def _trigger_next_run() -> bool:
    """Trigger the next Cloud Run Job execution of orchestrate-v2.

    Returns True if successfully triggered.
    """
    try:
        from google.cloud import run_v2
        from google.oauth2 import service_account

        sa_path = Path(__file__).resolve().parent.parent / "credentials" / "service_account.json"
        creds = service_account.Credentials.from_service_account_file(
            str(sa_path),
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        client = run_v2.JobsClient(credentials=creds)

        job_name = (
            f"projects/{GCP_PROJECT_ID}/locations/{GCP_REGION}"
            f"/jobs/orchestrate-v2"
        )
        client.run_job(name=job_name)
        logger.info("Continuous mode: triggered next run")
        return True
    except Exception as e:
        logger.error(f"Continuous mode: failed to trigger next run: {e}")
        return False


def _handle_continuous_mode(success: bool) -> None:
    """Handle continuous mode logic after pipeline completion.

    - On error: reset count, stop
    - On success: check count < max, increment, trigger next
    """
    enabled, count = _get_continuous_settings()

    if not enabled:
        logger.info("Continuous mode: disabled")
        if count > 0:
            _update_continuous_count(0)
        return

    if not success:
        logger.info("Continuous mode: stopping due to pipeline error")
        _update_continuous_count(0)
        notify(f"🔄 *連続実行停止* — エラー発生のため (実行回数: {count})")
        return

    new_count = count + 1
    if new_count >= CONTINUOUS_MAX_RUNS:
        logger.info(f"Continuous mode: reached max runs ({CONTINUOUS_MAX_RUNS})")
        _update_continuous_count(0)
        notify(f"🔄 *連続実行完了* — 最大{CONTINUOUS_MAX_RUNS}回に到達。カウントリセット済み")
        return

    _update_continuous_count(new_count)
    logger.info(f"Continuous mode: run {new_count}/{CONTINUOUS_MAX_RUNS}, cooldown {CONTINUOUS_COOLDOWN_SEC}s")
    notify(f"🔄 *連続実行* — {new_count}/{CONTINUOUS_MAX_RUNS}回目完了。{CONTINUOUS_COOLDOWN_SEC}秒後に次を開始")

    time.sleep(CONTINUOUS_COOLDOWN_SEC)

    if _trigger_next_run():
        logger.info("Continuous mode: next run triggered successfully")
    else:
        _update_continuous_count(0)
        notify("🔄 *連続実行停止* — 再トリガー失敗")


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def main():
    start_time = time.time()
    run_id = str(uuid.uuid4())

    logger.info("=" * 60)
    logger.info(f"V2 パイプライン開始 (run_id={run_id})")
    logger.info("=" * 60)
    update_status("orchestrate_v2", "running", f"パイプライン開始 (run_id={run_id[:8]})")

    try:
        # --- Setup ---
        settings = _load_settings()
        knowledge_context = get_knowledge_summary()

        # Save settings snapshot for reproducibility
        save_settings_snapshot(settings, run_id)

        steps: list[dict] = []

        # ===================================================================
        # A0: Micro-market generation
        # ===================================================================
        logger.info("=" * 40 + " A0: マイクロ市場生成")
        update_status("orchestrate_v2", "running", "A0: マイクロ市場生成中...")
        try:
            micro_markets = step_a0_generate_micro_markets(settings, knowledge_context, run_id)
            if not micro_markets:
                steps.append(_make_step_result("A0: マイクロ市場生成", STEP_FAIL,
                                               errors=["0件生成"]))
                _abort_pipeline(steps, run_id, start_time)
                return
            steps.append(_make_step_result("A0: マイクロ市場生成", STEP_OK,
                                           count=len(micro_markets), data=micro_markets))
        except Exception as e:
            steps.append(_make_step_result("A0: マイクロ市場生成", STEP_FAIL,
                                           errors=[str(e)]))
            _abort_pipeline(steps, run_id, start_time)
            return

        # ===================================================================
        # A1q: Quick gate
        # ===================================================================
        logger.info("=" * 40 + " A1q: 浅いゲート")
        update_status("orchestrate_v2", "running", f"A1q: {len(micro_markets)}市場をゲート判定中...")
        a1q_passed = []
        try:
            a1q_passed, a1q_all = step_a1_quick_gate(micro_markets, knowledge_context, run_id)
            if not a1q_passed:
                steps.append(_make_step_result("A1q: 浅いゲート", STEP_FAIL,
                                               count=0,
                                               errors=[f"全{len(micro_markets)}市場FAIL"]))
            else:
                steps.append(_make_step_result("A1q: 浅いゲート", STEP_OK,
                                               count=len(a1q_passed),
                                               data=a1q_passed))
        except Exception as e:
            logger.error(f"A1q exception (continuing): {e}")
            steps.append(_make_step_result("A1q: 浅いゲート", STEP_FAIL,
                                           errors=[str(e)]))

        # ===================================================================
        # A1d: Deep gate (max 5 markets)
        # ===================================================================
        passed_markets = []
        failed_markets = []
        if a1q_passed:
            logger.info("=" * 40 + " A1d: 深いゲート")
            update_status("orchestrate_v2", "running", f"A1d: {len(a1q_passed[:5])}市場を深いゲート判定中...")
            try:
                a1d_results, gate_log = step_a1_deep_gate(
                    a1q_passed, settings, knowledge_context, run_id
                )
                passed_markets = [r for r in a1d_results if r.get("status") == "PASS"]
                failed_markets = [r for r in a1d_results if r.get("status") != "PASS"]

                if passed_markets:
                    steps.append(_make_step_result("A1d: 深いゲート", STEP_OK,
                                                   count=len(passed_markets),
                                                   data=passed_markets))
                else:
                    steps.append(_make_step_result("A1d: 深いゲート", STEP_WARN,
                                                   count=0,
                                                   warnings=[f"全{len(a1q_passed[:5])}市場FAIL — 探索レーン確認中"]))
            except Exception as e:
                logger.error(f"A1d exception (continuing): {e}")
                steps.append(_make_step_result("A1d: 深いゲート", STEP_FAIL,
                                               errors=[str(e)]))
        else:
            steps.append(_make_step_result("A1d: 深いゲート", STEP_SKIP,
                                           warnings=["A1q PASS市場0件"]))

        # ===================================================================
        # EX: Exploration lane check
        # ===================================================================
        exploration = None
        if failed_markets:
            logger.info("=" * 40 + " EX: 探索レーン判定")
            update_status("orchestrate_v2", "running", "EX: 探索レーン判定中...")
            try:
                exploration = check_exploration_lane(failed_markets, run_id)
                if exploration:
                    steps.append(_make_step_result("EX: 探索レーン", STEP_OK,
                                                   count=1,
                                                   data=exploration))
                else:
                    steps.append(_make_step_result("EX: 探索レーン", STEP_SKIP,
                                                   warnings=["該当市場なし"]))
            except Exception as e:
                steps.append(_make_step_result("EX: 探索レーン", STEP_WARN,
                                               warnings=[str(e)]))

        # Check: do we have any market to proceed with?
        active_market = None
        if passed_markets:
            # Use first PASS market (同時1件ルール)
            active_market = passed_markets[0]
        elif exploration:
            active_market = exploration

        if not active_market:
            steps.append(_make_step_result("判定", STEP_FAIL,
                                           errors=["PASS市場0件 + 探索レーン0件 → C/0/LPスキップ"]))
            # Skip C/0/LP but still send final report (no abort)
            active_market_name = "N/A"
        else:
            active_market_name = active_market.get("micro_market", "unknown")
        logger.info(f"Active market: {active_market_name}")

        # ===================================================================
        # C: Competitor analysis (20 companies)
        # ===================================================================
        gap_top3 = []
        gate_result = {}
        micro_market_data = {}

        if not active_market:
            steps.append(_make_step_result("C: 競合20社", STEP_SKIP,
                                           warnings=["対象市場なし"]))
            steps.append(_make_step_result("0: オファー3案", STEP_SKIP,
                                           warnings=["対象市場なし"]))
        else:
            # ---------------------------------------------------------------
            # C: Competitor analysis (20 companies)
            # ---------------------------------------------------------------
            logger.info("=" * 40 + f" C: 競合20社分析 ({active_market_name})")
            update_status("orchestrate_v2", "running", f"C: {active_market_name} 競合20社分析中...")

            try:
                gate_rows = get_all_rows("gate_decision_log")
                for r in gate_rows:
                    if r.get("run_id") == run_id and r.get("micro_market") == active_market_name:
                        gate_result = r
                        break
            except Exception:
                pass

            try:
                micro_market_data = {
                    "micro_market": active_market_name,
                    "payer": gate_result.get("payer", ""),
                    "evidence_urls": gate_result.get("evidence_urls", ""),
                    "blackout_hypothesis": gate_result.get("blackout_hypothesis", ""),
                }

                analysis = analyze_competitors_20(
                    micro_market_data, gate_result, knowledge_context, run_id
                )
                comp_count = save_competitors_to_sheets(analysis, run_id, active_market_name)

                gap_top3 = analysis.get("gap_top3", [])

                # Save gap_top3 for offer generation
                gap_file = DATA_DIR / f"gap_top3_{run_id}.json"
                gap_file.write_text(json.dumps(gap_top3, ensure_ascii=False, indent=2), "utf-8")

                if comp_count >= 10:
                    steps.append(_make_step_result("C: 競合20社", STEP_OK,
                                                   count=comp_count, data=analysis))
                else:
                    steps.append(_make_step_result("C: 競合20社", STEP_WARN,
                                                   count=comp_count,
                                                   warnings=[f"{comp_count}社のみ（20社目標）"]))
            except Exception as e:
                logger.error(f"C exception (continuing): {e}")
                steps.append(_make_step_result("C: 競合20社", STEP_FAIL,
                                               errors=[str(e)]))

            # ---------------------------------------------------------------
            # 0: Offer generation (3 offers)
            # ---------------------------------------------------------------
            logger.info("=" * 40 + " 0: 即決オファー3案生成")
            update_status("orchestrate_v2", "running", "0: 即決オファー3案生成中...")

            try:
                from utils.learning_engine import get_learning_context
                from utils.validators import validate_offer_3

                learning_context = get_learning_context(categories=["idea_generation"])

                from jinja2 import Environment, FileSystemLoader
                from config import TEMPLATES_DIR
                from utils.claude_client import generate_json_with_retry

                offer_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
                template = offer_jinja_env.get_template("offer_3_prompt.j2")

                prompt = template.render(
                    micro_market_json=json.dumps(micro_market_data, ensure_ascii=False),
                    gap_top3_json=json.dumps(gap_top3, ensure_ascii=False),
                    gate_result_json=json.dumps(gate_result, ensure_ascii=False),
                    knowledge_context=knowledge_context,
                    learning_context=learning_context,
                )

                offers = generate_json_with_retry(
                    prompt=prompt,
                    system=(
                        "あなたは事業開発の専門家です。"
                        "スコアを出すな。7つの必須フィールドを全て埋めること。"
                        "架空の数値は禁止。必ず3案をJSON配列で出力すること。"
                    ),
                    max_tokens=8192,
                    temperature=0.5,
                    max_retries=3,
                    validator=validate_offer_3,
                )

                if isinstance(offers, dict):
                    offers = [offers]

                # Strict validation check
                vr = validate_offer_3(offers)
                if not vr.valid:
                    raise ValueError(f"オファー生成が不完全: {vr.errors}")

                # Save to sheets
                offer_rows: list[list] = []
                for offer in offers:
                    offer_rows.append([
                        run_id,
                        offer.get("offer_num", ""),
                        offer.get("payer", ""),
                        offer.get("offer_name", ""),
                        offer.get("deliverable", ""),
                        offer.get("time_to_value", ""),
                        offer.get("price", ""),
                        offer.get("replaces", ""),
                        offer.get("upsell", ""),
                    ])
                if offer_rows:
                    from utils.sheets_client import append_rows as _append
                    _append("offer_3_log", offer_rows)

                steps.append(_make_step_result("0: オファー3案", STEP_OK,
                                               count=len(offers), data=offers))
            except Exception as e:
                logger.error(f"0 exception (continuing): {e}")
                steps.append(_make_step_result("0: オファー3案", STEP_FAIL,
                                               errors=[str(e)]))

        # ===================================================================
        # LP: Readiness check
        # ===================================================================
        logger.info("=" * 40 + " LP: LP作成ガードチェック")
        update_status("orchestrate_v2", "running", "LP: LP作成ガードチェック中...")

        lp_check = check_lp_ready(run_id)
        if lp_check["status"] == "READY":
            steps.append(_make_step_result("LP: ガードチェック", STEP_OK))
        else:
            steps.append(_make_step_result("LP: ガードチェック", STEP_WARN,
                                           warnings=[f"BLOCKED: {', '.join(lp_check.get('missing', []))}"]))

        # ===================================================================
        # Report
        # ===================================================================
        elapsed = time.time() - start_time
        total_duration = f"{int(elapsed // 60)}分{int(elapsed % 60)}秒"

        # Count offers from step results
        _offer_count = next((s.get("count", 0) for s in steps if "オファー" in s["name"]), 0)
        send_pipeline_report(
            steps, run_id, lp_check, total_duration,
            passed_market_count=len(passed_markets),
            offer_count=_offer_count,
        )

        # Final status
        has_errors = any(s["status"] == STEP_FAIL for s in steps)
        final_status = "error" if has_errors else "success"
        step_summary = ", ".join(
            f"{s['name'].split(':')[0]}: {s.get('count', 0)}件" for s in steps if s.get("count")
        )

        # Build V2 metrics for dashboard display
        # Note: all values must be primitives (str/int/float) — no nested dicts
        #       because the dashboard renders {v} directly as React children
        v2_metrics: dict = {
            "run_id": run_id,
            "total_duration_sec": int(elapsed),
            "lp_status": lp_check["status"],
        }
        # Extract counts from each step for dashboard metric chips
        for s in steps:
            name = s["name"]
            count = s.get("count", 0)
            if "A0" in name:
                v2_metrics["micro_markets_generated"] = count
            elif "A1q" in name:
                v2_metrics["a1q_passed"] = count
                try:
                    v2_metrics["a1q_failed"] = len(micro_markets) - count
                except NameError:
                    v2_metrics["a1q_failed"] = 0
            elif "A1d" in name:
                v2_metrics["a1d_passed"] = count
                try:
                    v2_metrics["a1d_failed"] = len(a1q_passed[:5]) - count
                except NameError:
                    v2_metrics["a1d_failed"] = 0
            elif "探索レーン" in name:
                v2_metrics["exploration_lanes"] = count
            elif "競合" in name:
                v2_metrics["competitors_20"] = count
            elif "オファー" in name:
                v2_metrics["offers_generated"] = count
            elif "ガード" in name:
                if lp_check["status"] == "READY":
                    v2_metrics["lp_ready"] = 1
                else:
                    v2_metrics["lp_blocked"] = 1

        update_status(
            "orchestrate_v2", final_status,
            f"完了 ({total_duration}) — {step_summary}",
            v2_metrics,
        )
        logger.info(f"V2 パイプライン完了: {total_duration}")

        # Continuous mode: re-trigger if enabled
        _handle_continuous_mode(success=(not has_errors))

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"V2 Pipeline crashed: {e}")
        update_status("orchestrate_v2", "error", f"致命的エラー: {str(e)}")
        notify(f"🚨 *V2パイプライン致命的エラー*\n```{str(e)[:500]}```")
        # Continuous mode: stop on crash
        _handle_continuous_mode(success=False)
        raise


if __name__ == "__main__":
    main()
