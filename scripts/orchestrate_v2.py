"""
orchestrate_v2.py — V2 Evidence-gate pipeline orchestrator.

Flow (Phase 3):
  A0 → SV(検索需要) → C(20社+価格) → W(勝ち筋) → 0(3案) → U(UE) → PR → LP-guard
  → K(SEO KW) → S(GTM) → Notify.

Phase 2-3 changes:
  - A1q/A1d/EX removed → replaced by SV (search_volume.py)
  - Self-review after A0, C, and 0 steps
  - Priority scoring via priority_scorer.py
  - Competitor pricing scraping integrated in C step
  - W: Win strategy generation after competitor analysis
  - U: Agency unit economics after offer generation
  - K: SEO keyword research for LP-ready markets
  - S: Go-to-market plan for LP-ready markets

All scoring is **prohibited** for gate decisions.
Decisions are PASS/FAIL based on real data (search results, ads, URLs).
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
from typing import Any

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
    save_settings_snapshot,
)
from C_competitor_analysis import analyze_competitors_20, save_competitors_to_sheets, scrape_competitor_pricing
from utils.pdf_knowledge import get_knowledge_summary
from utils.search_volume import verify_batch as sv_verify_batch, ai_demand_deep_check
from utils.priority_scorer import score_markets as priority_score
from utils.win_strategy import generate_win_strategy
from utils.unit_economics import calculate_agency_ue
from utils.seo_keywords import research_keywords as seo_research
from utils.go_to_market import generate_gtm_plan
from utils.claude_client import generate_json_with_retry

logger = get_logger("orchestrate_v2", "orchestrate_v2.log")

# Step result constants
STEP_OK = "✅ 成功"
STEP_WARN = "⚠️ 警告あり"
STEP_FAIL = "❌ 失敗"
STEP_SKIP = "⏭️ スキップ"

# Sheet names for each step (for report links)
STEP_SHEET_MAP = {
    "A0": ["micro_market_list"],
    "SV": ["search_volume_log"],
    "C": ["competitor_20_log", "competitor_pricing_log"],
    "W": ["win_strategy_log"],
    "0": ["offer_3_log"],
    "U": ["unit_economics_log"],
    "PR": ["priority_score_log"],
    "K": ["seo_keywords_log"],
    "S": ["gtm_plan_log"],
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
# Self-review — AI checks its own output for quality
# ---------------------------------------------------------------------------

def _self_review(step_name: str, data: Any, context: str = "") -> dict:
    """Run AI self-review on step output.

    Returns {passed: bool, issues: list[str], suggestions: list[str]}.
    """
    if not data:
        return {"passed": True, "issues": [], "suggestions": []}

    data_sample = json.dumps(data, ensure_ascii=False, default=str)[:3000]

    prompt = (
        f"以下は「{step_name}」ステップの出力です。品質をレビューしてください。\n\n"
        f"出力データ（先頭3000文字）:\n{data_sample}\n\n"
        f"コンテキスト: {context}\n\n"
        f"以下をJSON形式で出力:\n"
        f'{{"passed": true/false,\n'
        f'  "issues": ["問題点1", "問題点2"],\n'
        f'  "suggestions": ["改善提案1"]}}\n\n'
        f"判定基準:\n"
        f"- 架空のURL/企業名がないか\n"
        f"- 必須フィールドが埋まっているか\n"
        f"- 業務代行型オファーの方針に合致しているか\n"
        f"- データの整合性があるか"
    )

    try:
        result = generate_json_with_retry(
            prompt=prompt,
            system="品質レビュアーとして、出力の問題点を指摘してください。問題なければpassedをtrueに。",
            max_tokens=2048,
            temperature=0.2,
            max_retries=1,
        )
        if isinstance(result, list):
            result = result[0] if result else {}
        return {
            "passed": result.get("passed", True),
            "issues": result.get("issues", []),
            "suggestions": result.get("suggestions", []),
        }
    except Exception as e:
        logger.warning(f"Self-review failed for {step_name}: {e}")
        return {"passed": True, "issues": [], "suggestions": [f"レビュー実行エラー: {e}"]}


# ---------------------------------------------------------------------------
# LP readiness check (local — no API call, direct Sheets check)
# ---------------------------------------------------------------------------

def check_lp_ready(run_id: str) -> dict:
    """Check if all conditions for LP creation are met.

    Phase 2 conditions:
    1. search_volume_log has PASS records for this run_id
    2. competitor_20_log has records for this run_id
    3. offer_3_log has 3 complete records for this run_id

    Returns dict with status (READY/BLOCKED) and missing items.
    """
    missing = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 1. Search volume check — at least 1 PASS market
    gate_ok = False
    is_exploration_only = False
    try:
        sv_rows = get_all_rows("search_volume_log")
        sv_pass = [r for r in sv_rows if r.get("run_id") == run_id and r.get("status") == "PASS"]
        if sv_pass:
            gate_ok = True
    except Exception:
        pass
    # Fallback: check old gate_decision_log for backward compat
    if not gate_ok:
        try:
            gate_rows = get_all_rows("gate_decision_log")
            gate_pass = [r for r in gate_rows if r.get("run_id") == run_id and r.get("status") == "PASS"]
            if gate_pass:
                gate_ok = True
        except Exception:
            pass
    if not gate_ok:
        missing.append("search_volume_log: PASS市場なし")

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
            # Self-review A0
            a0_review = _self_review("A0", micro_markets[:5], "マイクロ市場生成")
            a0_warnings = a0_review.get("issues", []) if not a0_review["passed"] else []
            steps.append(_make_step_result("A0: マイクロ市場生成",
                                           STEP_WARN if a0_warnings else STEP_OK,
                                           count=len(micro_markets),
                                           warnings=a0_warnings,
                                           data=micro_markets))
        except Exception as e:
            steps.append(_make_step_result("A0: マイクロ市場生成", STEP_FAIL,
                                           errors=[str(e)]))
            _abort_pipeline(steps, run_id, start_time)
            return

        # ===================================================================
        # SV: Search volume verification (replaces A1q + A1d + EX)
        # ===================================================================
        logger.info("=" * 40 + " SV: 検索需要検証")
        update_status("orchestrate_v2", "running", f"SV: {len(micro_markets)}市場の検索需要を検証中...")
        passed_markets = []
        try:
            sv_passed, sv_all = sv_verify_batch(micro_markets, run_id, max_markets=10)
            if not sv_passed:
                steps.append(_make_step_result("SV: 検索需要検証", STEP_FAIL,
                                               count=0,
                                               errors=[f"全{len(sv_all)}市場FAIL — 検索需要不足"]))
            else:
                steps.append(_make_step_result("SV: 検索需要検証", STEP_OK,
                                               count=len(sv_passed),
                                               data=sv_passed))
            passed_markets = sv_passed
        except Exception as e:
            logger.error(f"SV exception (continuing): {e}")
            steps.append(_make_step_result("SV: 検索需要検証", STEP_FAIL,
                                           errors=[str(e)]))

        # Check: do we have any market to proceed with?
        active_market = None
        if passed_markets:
            active_market = passed_markets[0]

        if not active_market:
            steps.append(_make_step_result("判定", STEP_FAIL,
                                           errors=["PASS市場0件 → C/0/LPスキップ"]))
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

            # Build context from SV results
            sv_evidence = active_market.get("evidence_urls", [])

            try:
                micro_market_data = {
                    "micro_market": active_market_name,
                    "payer": active_market.get("payer", ""),
                    "evidence_urls": json.dumps(sv_evidence, ensure_ascii=False) if isinstance(sv_evidence, list) else str(sv_evidence),
                    "blackout_hypothesis": "",
                }

                # Also check old gate_result for backward compat
                gate_result = {}
                try:
                    gate_rows = get_all_rows("gate_decision_log")
                    for r in gate_rows:
                        if r.get("run_id") == run_id and r.get("micro_market") == active_market_name:
                            gate_result = r
                            break
                except Exception:
                    pass

                analysis = analyze_competitors_20(
                    micro_market_data, gate_result, knowledge_context, run_id
                )
                comp_count = save_competitors_to_sheets(analysis, run_id, active_market_name)

                gap_top3 = analysis.get("gap_top3", [])

                # Save gap_top3 for offer generation
                gap_file = DATA_DIR / f"gap_top3_{run_id}.json"
                gap_file.write_text(json.dumps(gap_top3, ensure_ascii=False, indent=2), "utf-8")

                # Phase 2: Scrape competitor pricing
                competitors = analysis.get("competitors", [])
                if competitors:
                    logger.info(f"Scraping pricing for {len(competitors)} competitors...")
                    update_status("orchestrate_v2", "running", f"C: 価格スクレイピング中...")
                    scrape_competitor_pricing(competitors, run_id, active_market_name)

                # Self-review C
                c_review = _self_review("C: 競合20社", analysis, f"市場: {active_market_name}")
                c_warnings = c_review.get("issues", []) if not c_review["passed"] else []

                if comp_count >= 10:
                    steps.append(_make_step_result("C: 競合20社",
                                                   STEP_WARN if c_warnings else STEP_OK,
                                                   count=comp_count,
                                                   warnings=c_warnings,
                                                   data=analysis))
                else:
                    steps.append(_make_step_result("C: 競合20社", STEP_WARN,
                                                   count=comp_count,
                                                   warnings=[f"{comp_count}社のみ（20社目標）"] + c_warnings))
            except Exception as e:
                logger.error(f"C exception (continuing): {e}")
                steps.append(_make_step_result("C: 競合20社", STEP_FAIL,
                                               errors=[str(e)]))

            # ---------------------------------------------------------------
            # W: Win strategy generation
            # ---------------------------------------------------------------
            logger.info("=" * 40 + f" W: 勝ち筋戦略 ({active_market_name})")
            update_status("orchestrate_v2", "running", f"W: {active_market_name} 勝ち筋戦略策定中...")
            win_strategy = {}
            try:
                win_strategy = generate_win_strategy(
                    market_name=active_market_name,
                    run_id=run_id,
                    gap_top3=gap_top3,
                )
                if win_strategy and win_strategy.get("positioning"):
                    steps.append(_make_step_result("W: 勝ち筋戦略", STEP_OK,
                                                   count=len(win_strategy.get("action_items", [])),
                                                   data=win_strategy))
                else:
                    steps.append(_make_step_result("W: 勝ち筋戦略", STEP_WARN,
                                                   warnings=["戦略データ不完全"]))
            except Exception as e:
                logger.warning(f"W exception (non-fatal): {e}")
                steps.append(_make_step_result("W: 勝ち筋戦略", STEP_WARN,
                                               warnings=[str(e)]))

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

                # Self-review offers
                o_review = _self_review("0: オファー3案", offers, "業務代行型オファー")
                o_warnings = o_review.get("issues", []) if not o_review["passed"] else []

                steps.append(_make_step_result("0: オファー3案",
                                               STEP_WARN if o_warnings else STEP_OK,
                                               count=len(offers),
                                               warnings=o_warnings,
                                               data=offers))
            except Exception as e:
                logger.error(f"0 exception (continuing): {e}")
                steps.append(_make_step_result("0: オファー3案", STEP_FAIL,
                                               errors=[str(e)]))

        # ===================================================================
        # U: Agency unit economics (Phase 3)
        # ===================================================================
        if active_market:
            logger.info("=" * 40 + f" U: ユニットエコノミクス ({active_market_name})")
            update_status("orchestrate_v2", "running", f"U: {active_market_name} UE算出中...")
            try:
                # Get offers from step data
                offer_step = next((s for s in steps if "オファー" in s["name"]), None)
                offer_data = offer_step.get("data", []) if offer_step else []
                if offer_data:
                    ue_results = calculate_agency_ue(
                        market_name=active_market_name,
                        run_id=run_id,
                        offers=offer_data,
                    )
                    if ue_results:
                        steps.append(_make_step_result("U: UE算出", STEP_OK,
                                                       count=len(ue_results),
                                                       data=ue_results))
                    else:
                        steps.append(_make_step_result("U: UE算出", STEP_WARN,
                                                       warnings=["UE算出結果なし"]))
                else:
                    steps.append(_make_step_result("U: UE算出", STEP_SKIP,
                                                   warnings=["オファーデータなし"]))
            except Exception as e:
                logger.warning(f"U exception (non-fatal): {e}")
                steps.append(_make_step_result("U: UE算出", STEP_WARN,
                                               warnings=[str(e)]))

        # ===================================================================
        # PR: Priority scoring (Phase 2)
        # ===================================================================
        if passed_markets:
            logger.info("=" * 40 + " PR: 優先度スコアリング")
            update_status("orchestrate_v2", "running", "PR: 優先度スコアリング中...")
            try:
                scored = priority_score(run_id, passed_markets)
                if scored:
                    top = scored[0]
                    steps.append(_make_step_result("PR: 優先度", STEP_OK,
                                                   count=len(scored),
                                                   data={"top_market": top.get("micro_market", ""),
                                                         "tier": top.get("priority_tier", "")}))
                else:
                    steps.append(_make_step_result("PR: 優先度", STEP_SKIP,
                                                   warnings=["スコアリング対象なし"]))
            except Exception as e:
                logger.warning(f"PR exception (non-fatal): {e}")
                steps.append(_make_step_result("PR: 優先度", STEP_WARN,
                                               warnings=[str(e)]))

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
        # K: SEO keyword research (Phase 3) — only if LP READY
        # ===================================================================
        seo_kw_data = {}
        if lp_check["status"] == "READY" and active_market:
            logger.info("=" * 40 + f" K: SEOキーワード調査 ({active_market_name})")
            update_status("orchestrate_v2", "running", f"K: {active_market_name} SEOキーワード調査中...")
            try:
                seo_kw_data = seo_research(
                    market_name=active_market_name,
                    run_id=run_id,
                    industry=active_market.get("payer", ""),
                )
                kw_count = seo_kw_data.get("total_keywords", 0)
                cal_count = len(seo_kw_data.get("content_calendar", []))
                steps.append(_make_step_result("K: SEO KW", STEP_OK,
                                               count=kw_count,
                                               data={"calendar_entries": cal_count}))
            except Exception as e:
                logger.warning(f"K exception (non-fatal): {e}")
                steps.append(_make_step_result("K: SEO KW", STEP_WARN,
                                               warnings=[str(e)]))

        # ===================================================================
        # S: Go-to-market plan (Phase 3) — only if LP READY
        # ===================================================================
        if lp_check["status"] == "READY" and active_market:
            logger.info("=" * 40 + f" S: GTM計画 ({active_market_name})")
            update_status("orchestrate_v2", "running", f"S: {active_market_name} GTM計画策定中...")
            try:
                offer_step = next((s for s in steps if "オファー" in s["name"]), None)
                offer_data = offer_step.get("data", []) if offer_step else []
                gtm = generate_gtm_plan(
                    market_name=active_market_name,
                    run_id=run_id,
                    offers=offer_data if isinstance(offer_data, list) else [],
                    win_strategy=win_strategy if win_strategy else None,
                )
                ch_count = len(gtm.get("channels", []))
                steps.append(_make_step_result("S: GTM計画", STEP_OK,
                                               count=ch_count,
                                               data=gtm))
            except Exception as e:
                logger.warning(f"S exception (non-fatal): {e}")
                steps.append(_make_step_result("S: GTM計画", STEP_WARN,
                                               warnings=[str(e)]))

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
            elif "SV" in name:
                v2_metrics["sv_passed"] = count
                v2_metrics["sv_total"] = len(micro_markets) if micro_markets else 0
            elif "勝ち筋" in name:
                v2_metrics["win_strategy"] = 1 if count else 0
            elif "UE" in name:
                v2_metrics["ue_calculated"] = count
            elif "優先度" in name:
                v2_metrics["priority_scored"] = count
            elif "SEO" in name:
                v2_metrics["seo_keywords"] = count
            elif "GTM" in name:
                v2_metrics["gtm_channels"] = count
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
