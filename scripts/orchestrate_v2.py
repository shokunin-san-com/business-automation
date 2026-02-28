"""
orchestrate_v2.py — V2 Evidence-gate pipeline orchestrator.

3-Layer Exploration Engine:
  Phase A: Layer 1 — AI generates 100+ business model types (3 rounds)
  Phase B: Layer 2 — Cross types x construction needs → 500-1500 combos
  Phase C: Search demand verification for top combos
  Phase D: Competitor analysis (20 companies + pricing) for PASS combos
  Phase E: Offer generation (3 offers per combo)
  Phase F: Priority scoring
  Phase G: LP guard check → SEO KW → GTM → target collection

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
from config import DATA_DIR, GCP_PROJECT_ID, TEMPLATES_DIR, get_logger
from utils.sheets_client import (
    get_all_rows, append_rows, get_sheet_urls,
    get_setting, find_row_index, update_cell,
    ensure_sheet_exists,
)
from utils.slack_notifier import send_message as notify
from utils.status_writer import update_status

GCP_REGION = os.getenv("GCP_REGION", "asia-northeast1")
CONTINUOUS_MAX_RUNS = 10
CONTINUOUS_COOLDOWN_SEC = 60

# Import exploration engine
from utils.exploration_engine import (
    load_ceo_constraints, run_layer1, run_layer2,
    COMBOS_SHEET, COMBOS_HEADERS,
)

# Import downstream step modules
from A_market_research import save_settings_snapshot
from C_competitor_analysis import analyze_competitors_20, save_competitors_to_sheets, scrape_competitor_pricing
from utils.pdf_knowledge import get_knowledge_summary
from utils.search_volume import verify_batch as sv_verify_batch
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
    "A": ["business_model_types"],
    "B": ["business_combos"],
    "C": ["search_volume_log"],
    "D": ["competitor_20_log", "competitor_pricing_log"],
    "E": ["offer_3_log"],
    "F": ["priority_score_log"],
    "G": ["lp_ready_log"],
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
    """Run AI self-review on step output."""
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
# Adapter functions — convert combo format to existing module inputs
# ---------------------------------------------------------------------------

def _combos_to_market_format(combos: list[dict]) -> list[dict]:
    """Convert combos to the format expected by search_volume.verify_batch().

    verify_batch expects: [{micro_market, industry, task, intent_word, ...}]
    """
    markets = []
    for c in combos:
        name = c.get("business_name", "")
        target = c.get("target", "")
        markets.append({
            "micro_market": name,
            "industry": "建設業",
            "task": c.get("deliverable", ""),
            "intent_word": target,
            "payer": target,
            "combo_id": c.get("combo_id", ""),
            "type_id": c.get("type_id", ""),
            "type_name": c.get("type_name", ""),
        })
    return markets


def _combo_to_micro_market(combo: dict) -> dict:
    """Convert a combo to the format expected by analyze_competitors_20()."""
    return {
        "micro_market": combo.get("business_name", ""),
        "payer": combo.get("target", ""),
        "evidence_urls": "[]",
        "blackout_hypothesis": combo.get("monthly_300_path", ""),
    }


def _generate_combo_offers(
    combo: dict,
    run_id: str,
    knowledge_context: str,
    gap_top3: list,
) -> list[dict]:
    """Generate 3 offers for a combo using offer_3_prompt.j2 with combo context."""
    from jinja2 import Environment, FileSystemLoader
    from utils.validators import validate_offer_3

    offer_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = offer_env.get_template("offer_3_prompt.j2")

    micro_market_data = _combo_to_micro_market(combo)

    try:
        from utils.learning_engine import get_learning_context
        learning_context = get_learning_context(categories=["idea_generation"])
    except Exception:
        learning_context = ""

    prompt = template.render(
        micro_market_json=json.dumps(micro_market_data, ensure_ascii=False),
        gap_top3_json=json.dumps(gap_top3, ensure_ascii=False),
        gate_result_json=json.dumps({}, ensure_ascii=False),
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

    return offers


def _update_combo_verdicts(
    combos: list[dict],
    sv_results: list[dict],
    run_id: str,
) -> list[dict]:
    """Update business_combos sheet demand_verdict based on SV results.

    Returns list of PASS combos.
    """
    sv_pass_names = {r.get("micro_market", "") for r in sv_results}
    passed_combos = []

    for c in combos:
        name = c.get("business_name", "")
        verdict = "PASS" if name in sv_pass_names else "FAIL"
        c["demand_verdict"] = verdict
        if verdict == "PASS":
            passed_combos.append(c)

    # Batch update verdicts in sheet
    try:
        existing_rows = get_all_rows(COMBOS_SHEET)
        for row in existing_rows:
            if row.get("run_id") == run_id:
                bname = row.get("business_name", "")
                verdict = "PASS" if bname in sv_pass_names else "FAIL"
                row_idx = find_row_index(COMBOS_SHEET, "combo_id", row.get("combo_id", ""))
                if row_idx:
                    update_cell(COMBOS_SHEET, row_idx, 9, verdict)  # demand_verdict col
    except Exception as e:
        logger.warning(f"Failed to update combo verdicts in sheet: {e}")

    return passed_combos


# ---------------------------------------------------------------------------
# LP readiness check
# ---------------------------------------------------------------------------

def check_lp_ready(run_id: str) -> dict:
    """Check if all conditions for LP creation are met.

    Conditions:
    1. search_volume_log has PASS records for this run_id
    2. competitor_20_log has records for this run_id
    3. offer_3_log has 3 complete records for this run_id
    """
    missing = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 1. Search volume — at least 1 PASS
    gate_ok = False
    try:
        sv_rows = get_all_rows("search_volume_log")
        sv_pass = [r for r in sv_rows if r.get("run_id") == run_id and r.get("status") == "PASS"]
        if sv_pass:
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
        if len(comp_for_run) >= 10:
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

    try:
        append_rows("lp_ready_log", [[
            run_id, now,
            str(gate_ok), str(competitor_ok), str(offer_ok),
            status, blocked_reason,
        ]])
    except Exception as e:
        logger.warning(f"Failed to write lp_ready_log: {e}")

    return {
        "status": status,
        "gate_ok": gate_ok,
        "competitor_ok": competitor_ok,
        "offer_ok": offer_ok,
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
    passed_combo_count: int = 0,
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

    header = "🚀 *V2パイプライン完了（3Layer探索）*"
    if has_errors:
        header = "🚨 *V2パイプライン完了（エラーあり）*"
    elif has_warnings:
        header = "⚠️ *V2パイプライン完了（警告あり）*"

    lines = [
        header,
        f"⏱️ {total_duration}  |  🔑 run_id: `{run_id[:8]}`",
        "",
    ]

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

    lines.append("")
    lp_status = lp_check.get("status", "UNKNOWN")
    if lp_status == "READY":
        lines.append("🟢 *LP作成: READY* — 全条件クリア")
    else:
        lines.append(f"🔴 *LP作成: BLOCKED*")
        for m in lp_check.get("missing", []):
            lines.append(f"    → {m}")

    # CEO review notification
    ceo_items = []
    if passed_combo_count > 1:
        ceo_items.append(f"• PASSコンボが{passed_combo_count}件あります。優先度順で上位を選んでください。")
    if ceo_items and lp_status == "READY":
        lines.append("")
        lines.append("👔 *CEO承認が必要です*")
        for item in ceo_items:
            lines.append(f"    {item}")

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
    try:
        enabled = get_setting("v2_continuous_mode", "false").lower() == "true"
        count = int(get_setting("v2_continuous_count", "0"))
        return enabled, count
    except Exception as e:
        logger.warning(f"Failed to read continuous settings: {e}")
        return False, 0


def _update_continuous_count(new_count: int) -> None:
    try:
        row = find_row_index("settings", "key", "v2_continuous_count")
        if row:
            update_cell("settings", row, 2, str(new_count))
        else:
            append_rows("settings", [["v2_continuous_count", str(new_count)]])
    except Exception as e:
        logger.warning(f"Failed to update continuous count: {e}")


def _trigger_next_run() -> bool:
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
# Main orchestrator — 3-Layer Exploration Pipeline
# ---------------------------------------------------------------------------

def main():
    start_time = time.time()
    run_id = str(uuid.uuid4())

    logger.info("=" * 60)
    logger.info(f"V2 パイプライン開始 — 3Layer探索 (run_id={run_id})")
    logger.info("=" * 60)
    update_status("orchestrate_v2", "running", f"パイプライン開始 (run_id={run_id[:8]})")

    try:
        # --- Setup ---
        settings = _load_settings()
        knowledge_context = get_knowledge_summary()
        save_settings_snapshot(settings, run_id)

        ceo_constraints = load_ceo_constraints(settings)
        max_sv_combos = int(settings.get("max_sv_combos", "50"))
        max_competitor_combos = int(settings.get("max_competitor_combos", "5"))

        steps: list[dict] = []

        # ===================================================================
        # Phase A: Layer 1 — Business model type generation (100+ types)
        # ===================================================================
        logger.info("=" * 40 + " Phase A: Layer 1 型生成")
        update_status("orchestrate_v2", "running", "A: Layer 1 ビジネスモデル型生成中...")
        try:
            all_types = run_layer1(
                ceo_constraints=ceo_constraints,
                knowledge_context=knowledge_context,
                run_id=run_id,
                rounds=3,
                target_per_round=35,
            )
            if not all_types:
                steps.append(_make_step_result("A: Layer1型生成", STEP_FAIL,
                                               errors=["0型生成"]))
                _abort_pipeline(steps, run_id, start_time)
                return

            steps.append(_make_step_result("A: Layer1型生成", STEP_OK,
                                           count=len(all_types),
                                           data=all_types))
        except Exception as e:
            steps.append(_make_step_result("A: Layer1型生成", STEP_FAIL,
                                           errors=[str(e)]))
            _abort_pipeline(steps, run_id, start_time)
            return

        # ===================================================================
        # Phase B: Layer 2 — Type x Needs combo generation
        # ===================================================================
        logger.info("=" * 40 + f" Phase B: Layer 2 コンボ生成 ({len(all_types)}型)")
        update_status("orchestrate_v2", "running", f"B: {len(all_types)}型のコンボ生成中...")
        all_combos: list[dict] = []
        try:
            all_combos = run_layer2(
                types=all_types,
                ceo_constraints=ceo_constraints,
                knowledge_context=knowledge_context,
                run_id=run_id,
                batch_size=5,
            )
            if not all_combos:
                steps.append(_make_step_result("B: Layer2コンボ", STEP_FAIL,
                                               errors=["0コンボ生成"]))
                _abort_pipeline(steps, run_id, start_time)
                return

            steps.append(_make_step_result("B: Layer2コンボ", STEP_OK,
                                           count=len(all_combos),
                                           data=all_combos))
        except Exception as e:
            steps.append(_make_step_result("B: Layer2コンボ", STEP_FAIL,
                                           errors=[str(e)]))
            _abort_pipeline(steps, run_id, start_time)
            return

        # ===================================================================
        # Phase C: Search demand verification for top combos
        # ===================================================================
        combo_markets = _combos_to_market_format(all_combos[:max_sv_combos])
        logger.info("=" * 40 + f" Phase C: 検索需要検証 ({len(combo_markets)}コンボ)")
        update_status("orchestrate_v2", "running", f"C: {len(combo_markets)}コンボの検索需要検証中...")

        passed_combos: list[dict] = []
        try:
            sv_passed, sv_all = sv_verify_batch(combo_markets, run_id, max_markets=max_sv_combos)
            if not sv_passed:
                steps.append(_make_step_result("C: 検索需要検証", STEP_FAIL,
                                               count=0,
                                               errors=[f"全{len(sv_all)}コンボFAIL"]))
            else:
                steps.append(_make_step_result("C: 検索需要検証", STEP_OK,
                                               count=len(sv_passed),
                                               data=sv_passed))

            # Update combo verdicts in sheet
            passed_combos = _update_combo_verdicts(all_combos[:max_sv_combos], sv_passed or [], run_id)
        except Exception as e:
            logger.error(f"Phase C exception: {e}")
            steps.append(_make_step_result("C: 検索需要検証", STEP_FAIL,
                                           errors=[str(e)]))

        if not passed_combos:
            steps.append(_make_step_result("判定", STEP_FAIL,
                                           errors=["PASSコンボ0件 → D/E/F/Gスキップ"]))

        # ===================================================================
        # Phase D: Competitor analysis for top PASS combos
        # ===================================================================
        d_combos = passed_combos[:max_competitor_combos]
        all_gap_top3: list = []
        all_analysis: list = []

        if not d_combos:
            steps.append(_make_step_result("D: 競合分析", STEP_SKIP,
                                           warnings=["PASSコンボなし"]))
        else:
            logger.info("=" * 40 + f" Phase D: 競合分析 ({len(d_combos)}コンボ)")
            update_status("orchestrate_v2", "running", f"D: {len(d_combos)}コンボの競合分析中...")

            total_comp_count = 0
            for combo in d_combos:
                combo_name = combo.get("business_name", "unknown")
                logger.info(f"  D: 競合分析 — {combo_name}")

                try:
                    mm_data = _combo_to_micro_market(combo)
                    analysis = analyze_competitors_20(
                        mm_data, {}, knowledge_context, run_id
                    )
                    comp_count = save_competitors_to_sheets(analysis, run_id, combo_name)
                    total_comp_count += comp_count

                    gap3 = analysis.get("gap_top3", [])
                    all_gap_top3.extend(gap3)
                    all_analysis.append({"combo": combo, "analysis": analysis, "gap_top3": gap3})

                    # Scrape competitor pricing
                    competitors = analysis.get("competitors", [])
                    if competitors:
                        scrape_competitor_pricing(competitors, run_id, combo_name)

                    time.sleep(1.0)
                except Exception as e:
                    logger.warning(f"D failed for {combo_name}: {e}")

            if total_comp_count >= 10:
                steps.append(_make_step_result("D: 競合分析", STEP_OK,
                                               count=total_comp_count))
            elif total_comp_count > 0:
                steps.append(_make_step_result("D: 競合分析", STEP_WARN,
                                               count=total_comp_count,
                                               warnings=[f"{total_comp_count}社（20社目標）"]))
            else:
                steps.append(_make_step_result("D: 競合分析", STEP_FAIL,
                                               errors=["競合データ取得失敗"]))

        # ===================================================================
        # Phase E: Offer generation for top PASS combos
        # ===================================================================
        all_offers: list[dict] = []

        if not d_combos:
            steps.append(_make_step_result("E: オファー生成", STEP_SKIP,
                                           warnings=["PASSコンボなし"]))
        else:
            logger.info("=" * 40 + f" Phase E: オファー生成 ({len(d_combos)}コンボ)")
            update_status("orchestrate_v2", "running", f"E: {len(d_combos)}コンボのオファー生成中...")

            for idx, combo in enumerate(d_combos):
                combo_name = combo.get("business_name", "unknown")
                logger.info(f"  E: オファー生成 — {combo_name}")

                # Find gap_top3 for this combo
                combo_gaps = []
                for a in all_analysis:
                    if a["combo"].get("combo_id") == combo.get("combo_id"):
                        combo_gaps = a.get("gap_top3", [])
                        break

                try:
                    offers = _generate_combo_offers(
                        combo=combo,
                        run_id=run_id,
                        knowledge_context=knowledge_context,
                        gap_top3=combo_gaps or all_gap_top3[:3],
                    )

                    # Save to sheets
                    offer_rows = []
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
                        append_rows("offer_3_log", offer_rows)

                    all_offers.extend(offers)
                    time.sleep(1.0)
                except Exception as e:
                    logger.warning(f"E failed for {combo_name}: {e}")

            if all_offers:
                steps.append(_make_step_result("E: オファー生成", STEP_OK,
                                               count=len(all_offers),
                                               data=all_offers))
            else:
                steps.append(_make_step_result("E: オファー生成", STEP_FAIL,
                                               errors=["オファー生成失敗"]))

        # ===================================================================
        # Phase F: Priority scoring
        # ===================================================================
        if passed_combos:
            logger.info("=" * 40 + " Phase F: 優先度スコアリング")
            update_status("orchestrate_v2", "running", "F: 優先度スコアリング中...")

            # Convert passed combos to market-like format for priority_score
            sv_market_format = _combos_to_market_format(passed_combos)
            try:
                scored = priority_score(run_id, sv_market_format)
                if scored:
                    top = scored[0]
                    steps.append(_make_step_result("F: 優先度", STEP_OK,
                                                   count=len(scored),
                                                   data={"top": top.get("micro_market", ""),
                                                         "tier": top.get("priority_tier", "")}))
                else:
                    steps.append(_make_step_result("F: 優先度", STEP_SKIP,
                                                   warnings=["スコアリング対象なし"]))
            except Exception as e:
                logger.warning(f"F exception: {e}")
                steps.append(_make_step_result("F: 優先度", STEP_WARN,
                                               warnings=[str(e)]))
        else:
            steps.append(_make_step_result("F: 優先度", STEP_SKIP,
                                           warnings=["PASSコンボなし"]))

        # ===================================================================
        # Phase G: LP guard → SEO KW → GTM → target collection
        # ===================================================================
        logger.info("=" * 40 + " Phase G: LP/SEO/GTM")
        update_status("orchestrate_v2", "running", "G: LPガードチェック中...")

        lp_check = check_lp_ready(run_id)
        if lp_check["status"] == "READY":
            steps.append(_make_step_result("G: LPガード", STEP_OK))

            # --- SEO keyword research ---
            top_combo = d_combos[0] if d_combos else None
            if top_combo:
                top_name = top_combo.get("business_name", "")
                logger.info(f"  G-K: SEOキーワード調査 ({top_name})")
                update_status("orchestrate_v2", "running", f"G-K: SEO KW調査中...")
                try:
                    seo_data = seo_research(
                        market_name=top_name,
                        run_id=run_id,
                        industry=top_combo.get("target", ""),
                    )
                    kw_count = seo_data.get("total_keywords", 0)
                    steps.append(_make_step_result("G: SEO KW", STEP_OK,
                                                   count=kw_count))
                except Exception as e:
                    logger.warning(f"G-K exception: {e}")
                    steps.append(_make_step_result("G: SEO KW", STEP_WARN,
                                                   warnings=[str(e)]))

                # --- GTM plan ---
                logger.info(f"  G-S: GTM計画 ({top_name})")
                update_status("orchestrate_v2", "running", f"G-S: GTM計画策定中...")
                try:
                    win_strategy = {}
                    try:
                        win_strategy = generate_win_strategy(
                            market_name=top_name,
                            run_id=run_id,
                            gap_top3=all_gap_top3[:3],
                        )
                    except Exception:
                        pass

                    gtm = generate_gtm_plan(
                        market_name=top_name,
                        run_id=run_id,
                        offers=all_offers[:3] if all_offers else [],
                        win_strategy=win_strategy if win_strategy else None,
                    )
                    ch_count = len(gtm.get("channels", []))
                    steps.append(_make_step_result("G: GTM計画", STEP_OK,
                                                   count=ch_count))
                except Exception as e:
                    logger.warning(f"G-S exception: {e}")
                    steps.append(_make_step_result("G: GTM計画", STEP_WARN,
                                                   warnings=[str(e)]))

                # --- Target collection ---
                logger.info(f"  G-T: ターゲット収集 ({top_name})")
                update_status("orchestrate_v2", "running", f"G-T: ターゲット収集中...")
                try:
                    from utils.target_collector import collect_and_register
                    registered = collect_and_register(
                        business_id=run_id[:8],
                        market_name=top_name,
                        payer=top_combo.get("target", ""),
                        target_count=20,
                    )
                    if registered:
                        steps.append(_make_step_result("G: ターゲット収集", STEP_OK,
                                                       count=registered))
                except Exception as e:
                    logger.warning(f"G-T exception: {e}")
                    steps.append(_make_step_result("G: ターゲット収集", STEP_WARN,
                                                   warnings=[str(e)]))
        else:
            steps.append(_make_step_result("G: LPガード", STEP_WARN,
                                           warnings=[f"BLOCKED: {', '.join(lp_check.get('missing', []))}"]))

        # ===================================================================
        # Report
        # ===================================================================
        elapsed = time.time() - start_time
        total_duration = f"{int(elapsed // 60)}分{int(elapsed % 60)}秒"

        send_pipeline_report(
            steps, run_id, lp_check, total_duration,
            passed_combo_count=len(passed_combos),
            offer_count=len(all_offers),
        )

        # Final status
        has_errors = any(s["status"] == STEP_FAIL for s in steps)
        final_status = "error" if has_errors else "success"
        step_summary = ", ".join(
            f"{s['name'].split(':')[0]}: {s.get('count', 0)}件" for s in steps if s.get("count")
        )

        v2_metrics: dict = {
            "run_id": run_id,
            "total_duration_sec": int(elapsed),
            "lp_status": lp_check["status"],
        }
        for s in steps:
            name = s["name"]
            count = s.get("count", 0)
            if "Layer1" in name:
                v2_metrics["types_generated"] = count
            elif "Layer2" in name:
                v2_metrics["combos_generated"] = count
            elif "検索需要" in name:
                v2_metrics["sv_passed"] = count
            elif "競合" in name:
                v2_metrics["competitors_analyzed"] = count
            elif "オファー" in name:
                v2_metrics["offers_generated"] = count
            elif "優先度" in name:
                v2_metrics["priority_scored"] = count
            elif "SEO" in name:
                v2_metrics["seo_keywords"] = count
            elif "GTM" in name:
                v2_metrics["gtm_channels"] = count
            elif "ターゲット" in name:
                v2_metrics["targets_collected"] = count
            elif "LPガード" in name:
                v2_metrics["lp_ready"] = 1 if lp_check["status"] == "READY" else 0

        update_status(
            "orchestrate_v2", final_status,
            f"完了 ({total_duration}) — {step_summary}",
            v2_metrics,
        )
        logger.info(f"V2 パイプライン完了: {total_duration}")

        _handle_continuous_mode(success=(not has_errors))

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"V2 Pipeline crashed: {e}")
        update_status("orchestrate_v2", "error", f"致命的エラー: {str(e)}")
        notify(f"🚨 *V2パイプライン致命的エラー*\n```{str(e)[:500]}```")
        _handle_continuous_mode(success=False)
        raise


if __name__ == "__main__":
    main()
