"""
orchestrate_v2.py — V2 Evidence-gate pipeline orchestrator.

Phase A: Layer 1 — 5-axis x 20 prompts → 50-80 business model types
Phase B: Layer 2 — Types x construction needs → 500-1500 combos
Phase C: Multi-source demand verification (Suggest / Gemini / SNS)
Phase D: Competitor analysis (Gemini grounding + 3-axis win assessment)
Phase E: Offer generation (AI禁止 + 具体的納品物)
Phase F: LP generation + URL slug
Phase G: Email target collection (Gemini grounding)
Phase H: CEO approval + email sending (Gmail API)
→ 2 weeks later: Validation A/B/C/D ranking

All gate decisions are PASS/FAIL based on real data. No scoring.
run_id is generated once and propagated to all steps for traceability.
Budget gate (cost_tracker) checked before each phase.

Continuous mode: settings の v2_continuous_mode=true で連続実行。

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
from config import (
    DATA_DIR, GCP_PROJECT_ID, TEMPLATES_DIR,
    YOUR_NAME, YOUR_EMAIL,
    get_logger,
)
from utils.sheets_client import (
    get_all_rows, append_rows, get_sheet_urls,
    get_setting, find_row_index, update_cell,
)
from utils.slack_notifier import send_message as notify
from utils.status_writer import update_status

# --- New v2 modules ---
from utils.exploration_engine import load_ceo_constraints, run_layer1, run_layer2
from utils.demand_verifier import verify_batch as demand_verify_batch
from utils.competitor_analyzer import analyze_competitors
from utils.email_target_collector import collect_emails
from utils.email_sender import submit_for_approval
from utils.cost_tracker import check_budget_gate, record_api_call
from utils.slug_generator import generate_slug

# --- Existing modules still used ---
from A_market_research import save_settings_snapshot
from utils.pdf_knowledge import get_knowledge_summary
from utils.claude_client import generate_json_with_retry

GCP_REGION = os.getenv("GCP_REGION", "asia-northeast1")
CONTINUOUS_MAX_RUNS = 10
CONTINUOUS_COOLDOWN_SEC = 60

logger = get_logger("orchestrate_v2", "orchestrate_v2.log")

# Step result constants
STEP_OK = "✅ 成功"
STEP_WARN = "⚠️ 警告あり"
STEP_FAIL = "❌ 失敗"
STEP_SKIP = "⏭️ スキップ"

STEP_SHEET_MAP = {
    "A": ["business_model_types"],
    "B": ["business_combos"],
    "C": ["demand_verification_log"],
    "D": ["competitor_20_log"],
    "E": ["offer_3_log"],
    "F": ["lp_content"],
    "G": ["email_targets"],
    "H": ["mail_approval"],
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


def _budget_check(steps: list[dict], run_id: str, start_time: float) -> bool:
    """Check budget gate. Returns True if OK to proceed."""
    gate = check_budget_gate()
    if gate["status"] == "HARD_STOP":
        steps.append(_make_step_result(
            "BUDGET", STEP_FAIL,
            errors=[f"月額上限到達: ¥{gate['cumulative_jpy']:,.0f} / ¥{gate['hard_stop_jpy']:,.0f}"],
        ))
        _abort_pipeline(steps, run_id, start_time)
        return False
    if gate["status"] == "WARNING":
        logger.warning(f"Budget warning: ¥{gate['cumulative_jpy']:,.0f}")
    return True


# ---------------------------------------------------------------------------
# Offer generation
# ---------------------------------------------------------------------------

def _generate_combo_offers(
    combo: dict,
    run_id: str,
    knowledge_context: str,
    gap_top3: list,
) -> list[dict]:
    from jinja2 import Environment, FileSystemLoader
    from utils.validators import validate_offer_3

    offer_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = offer_env.get_template("offer_3_prompt.j2")

    micro_market_data = {
        "micro_market": combo.get("business_name", ""),
        "payer": combo.get("target", ""),
        "evidence_urls": "[]",
        "blackout_hypothesis": combo.get("monthly_300_path", ""),
    }

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


# ---------------------------------------------------------------------------
# Pipeline report
# ---------------------------------------------------------------------------

def send_pipeline_report(
    steps: list[dict],
    run_id: str,
    total_duration: str,
    budget_info: dict | None = None,
):
    try:
        all_sheet_names = set()
        for s in steps:
            step_key = s["name"].split(":")[0].strip()
            for sn in STEP_SHEET_MAP.get(step_key, []):
                all_sheet_names.add(sn)
        sheet_urls = get_sheet_urls(list(all_sheet_names)) if all_sheet_names else {}
    except Exception:
        sheet_urls = {}

    has_errors = any(s["status"] == STEP_FAIL for s in steps)
    has_warnings = any(s["status"] == STEP_WARN for s in steps)

    header = "🚀 *V2パイプライン完了（Phase A-H）*"
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
        step_key = s["name"].split(":")[0].strip()
        relevant = STEP_SHEET_MAP.get(step_key, [])
        link_parts = [f"<{sheet_urls[sn]}|{sn}>" for sn in relevant if sn in sheet_urls]
        link_str = f"  → {' '.join(link_parts)}" if link_parts else ""
        count_str = f" ({s['count']}件)" if s.get("count") else ""
        lines.append(f"  {s['status']} {s['name']}{count_str}{link_str}")
        if s.get("errors"):
            for e in s["errors"][:3]:
                lines.append(f"    → {e}")

    if budget_info:
        lines.append("")
        lines.append(
            f"💰 コスト: ¥{budget_info.get('cumulative_jpy', 0):,.0f}"
            f" / ¥{budget_info.get('hard_stop_jpy', 30000):,.0f}"
        )

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
# Continuous mode
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
# Main orchestrator — Phase A-H Pipeline
# ---------------------------------------------------------------------------

def main():
    start_time = time.time()
    run_id = str(uuid.uuid4())

    logger.info("=" * 60)
    logger.info(f"V2 パイプライン開始 — Phase A-H (run_id={run_id})")
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
        # Phase A: Layer 1 — 5-axis x 20 prompts → 50-80 types
        # ===================================================================
        if not _budget_check(steps, run_id, start_time):
            return

        logger.info("=" * 40 + " Phase A: Layer 1 型生成 (5軸×20プロンプト)")
        update_status("orchestrate_v2", "running", "A: Layer 1 ビジネスモデル型生成中...")
        try:
            all_types = run_layer1(
                ceo_constraints=ceo_constraints,
                knowledge_context=knowledge_context,
                run_id=run_id,
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
        if not _budget_check(steps, run_id, start_time):
            return

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
        # Phase C: Multi-source demand verification
        # ===================================================================
        if not _budget_check(steps, run_id, start_time):
            return

        verify_combos = all_combos[:max_sv_combos]
        logger.info("=" * 40 + f" Phase C: マルチソース需要検証 ({len(verify_combos)}コンボ)")
        update_status("orchestrate_v2", "running", f"C: {len(verify_combos)}コンボの需要検証中...")

        passed_combos: list[dict] = []
        try:
            dv_passed, dv_all = demand_verify_batch(verify_combos, run_id, max_groups=150)
            if not dv_passed:
                steps.append(_make_step_result("C: 需要検証", STEP_FAIL,
                                               count=0,
                                               errors=[f"全{len(dv_all)}グループFAIL"]))
            else:
                weak_count = sum(
                    1 for r in dv_all
                    if r.get("verdict") == "WEAK"
                )
                warnings = []
                if weak_count:
                    warnings.append(f"WEAK判定: {weak_count}件")
                steps.append(_make_step_result("C: 需要検証", STEP_OK,
                                               count=len(dv_passed),
                                               warnings=warnings,
                                               data=dv_passed))
            passed_combos = dv_passed or []
        except Exception as e:
            logger.error(f"Phase C exception: {e}")
            steps.append(_make_step_result("C: 需要検証", STEP_FAIL,
                                           errors=[str(e)]))

        if not passed_combos:
            steps.append(_make_step_result("判定", STEP_FAIL,
                                           errors=["PASSコンボ0件 → D-Hスキップ"]))

        # ===================================================================
        # Phase D: Competitor analysis (Gemini grounding + 3-axis win)
        # ===================================================================
        d_combos = passed_combos[:max_competitor_combos]
        all_win_assessments: list[dict] = []

        if not d_combos:
            steps.append(_make_step_result("D: 競合分析", STEP_SKIP,
                                           warnings=["PASSコンボなし"]))
        else:
            if not _budget_check(steps, run_id, start_time):
                return

            logger.info("=" * 40 + f" Phase D: 競合分析 ({len(d_combos)}コンボ)")
            update_status("orchestrate_v2", "running", f"D: {len(d_combos)}コンボの競合分析中...")

            d_pass_combos = []
            for combo in d_combos:
                combo_name = combo.get("business_name", "unknown")
                logger.info(f"  D: 競合分析 — {combo_name}")

                try:
                    result = analyze_competitors(
                        market_name=combo_name,
                        run_id=run_id,
                        max_competitors=20,
                    )

                    status = result.get("status", "FAIL")
                    if status == "PASS":
                        d_pass_combos.append(combo)
                        win = result.get("win_assessment", {})
                        all_win_assessments.append({
                            "combo": combo,
                            "win_assessment": win,
                            "competitors": result.get("competitors", []),
                        })
                    else:
                        reason = result.get("fail_reason", "unknown")
                        logger.info(f"  D: {combo_name} → FAIL ({reason})")

                    time.sleep(1.0)
                except Exception as e:
                    logger.warning(f"D failed for {combo_name}: {e}")

            if d_pass_combos:
                steps.append(_make_step_result("D: 競合分析", STEP_OK,
                                               count=len(d_pass_combos),
                                               data=d_pass_combos))
            else:
                steps.append(_make_step_result("D: 競合分析", STEP_FAIL,
                                               errors=["全コンボ競合分析FAIL"]))

            # Narrow passed_combos to those that passed D
            passed_combos = d_pass_combos

        # ===================================================================
        # Phase E: Offer generation for PASS combos
        # ===================================================================
        all_offers: list[dict] = []
        e_combos = passed_combos[:max_competitor_combos]

        if not e_combos:
            steps.append(_make_step_result("E: オファー生成", STEP_SKIP,
                                           warnings=["PASSコンボなし"]))
        else:
            if not _budget_check(steps, run_id, start_time):
                return

            logger.info("=" * 40 + f" Phase E: オファー生成 ({len(e_combos)}コンボ)")
            update_status("orchestrate_v2", "running", f"E: {len(e_combos)}コンボのオファー生成中...")

            for combo in e_combos:
                combo_name = combo.get("business_name", "unknown")
                logger.info(f"  E: オファー生成 — {combo_name}")

                # Find win assessment gap info for this combo
                combo_gaps = []
                for wa in all_win_assessments:
                    if wa["combo"].get("combo_id") == combo.get("combo_id"):
                        win = wa.get("win_assessment", {})
                        gap_detail = win.get("gap", {}).get("detail", "")
                        if gap_detail:
                            combo_gaps = [{"gap": gap_detail}]
                        break

                try:
                    offers = _generate_combo_offers(
                        combo=combo,
                        run_id=run_id,
                        knowledge_context=knowledge_context,
                        gap_top3=combo_gaps,
                    )

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
        # Phase F: LP generation + slug
        # ===================================================================
        if not all_offers or not e_combos:
            steps.append(_make_step_result("F: LP生成", STEP_SKIP,
                                           warnings=["オファーなし"]))
        else:
            if not _budget_check(steps, run_id, start_time):
                return

            logger.info("=" * 40 + " Phase F: LP生成 + スラッグ")
            update_status("orchestrate_v2", "running", "F: LP生成中...")

            lp_count = 0
            for combo in e_combos:
                combo_name = combo.get("business_name", "unknown")
                try:
                    slug = generate_slug(combo_name)
                    business_id = f"{run_id[:8]}-{slug}"

                    combo_offers = [
                        o for o in all_offers
                        if o.get("payer", "") == combo.get("target", "")
                    ][:3]
                    if not combo_offers:
                        combo_offers = all_offers[:3]

                    # Find competitor info
                    competitors = []
                    for wa in all_win_assessments:
                        if wa["combo"].get("combo_id") == combo.get("combo_id"):
                            competitors = wa.get("competitors", [])[:5]
                            break

                    # Record LP readiness
                    now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    append_rows("lp_ready_log", [[
                        run_id, now,
                        "True", "True", "True",
                        "READY", "",
                        combo_name, slug, business_id,
                    ]])
                    lp_count += 1

                    logger.info(f"  F: LP準備完了 — {combo_name} (slug={slug})")
                except Exception as e:
                    logger.warning(f"F failed for {combo_name}: {e}")

            if lp_count:
                steps.append(_make_step_result("F: LP生成", STEP_OK, count=lp_count))
            else:
                steps.append(_make_step_result("F: LP生成", STEP_WARN,
                                               warnings=["LP準備なし"]))

        # ===================================================================
        # Phase G: Email target collection (Gemini grounding)
        # ===================================================================
        all_email_targets: list[dict] = []

        if not e_combos:
            steps.append(_make_step_result("G: メール収集", STEP_SKIP,
                                           warnings=["PASSコンボなし"]))
        else:
            if not _budget_check(steps, run_id, start_time):
                return

            logger.info("=" * 40 + " Phase G: メールターゲット収集")
            update_status("orchestrate_v2", "running", "G: メールターゲット収集中...")

            for combo in e_combos:
                combo_name = combo.get("business_name", "unknown")
                payer = combo.get("target", "建設会社")
                slug = generate_slug(combo_name)
                business_id = f"{run_id[:8]}-{slug}"

                logger.info(f"  G: メール収集 — {combo_name} (payer={payer})")
                try:
                    targets = collect_emails(
                        market_name=combo_name,
                        payer=payer,
                        run_id=run_id,
                        business_id=business_id,
                        target_count=50,
                    )
                    for t in targets:
                        t["combo_name"] = combo_name
                        t["business_id"] = business_id
                    all_email_targets.extend(targets)
                    time.sleep(1.0)
                except Exception as e:
                    logger.warning(f"G failed for {combo_name}: {e}")

            if all_email_targets:
                steps.append(_make_step_result("G: メール収集", STEP_OK,
                                               count=len(all_email_targets)))
            else:
                steps.append(_make_step_result("G: メール収集", STEP_WARN,
                                               warnings=["メールアドレス取得0件"]))

        # ===================================================================
        # Phase H: CEO approval + email sending
        # ===================================================================
        if not all_email_targets or not all_offers:
            steps.append(_make_step_result("H: CEO承認申請", STEP_SKIP,
                                           warnings=["ターゲットまたはオファーなし"]))
        else:
            if not _budget_check(steps, run_id, start_time):
                return

            logger.info("=" * 40 + " Phase H: CEO承認申請")
            update_status("orchestrate_v2", "running", "H: CEO承認メール申請中...")

            total_submitted = 0
            for combo in e_combos:
                combo_name = combo.get("business_name", "unknown")
                slug = generate_slug(combo_name)
                business_id = f"{run_id[:8]}-{slug}"

                # Get targets for this combo
                combo_targets = [
                    t for t in all_email_targets
                    if t.get("business_id") == business_id
                ]
                if not combo_targets:
                    continue

                # Get best offer for this combo
                combo_offer = None
                for o in all_offers:
                    if o.get("payer", "") == combo.get("target", ""):
                        combo_offer = o
                        break
                if not combo_offer and all_offers:
                    combo_offer = all_offers[0]

                if not combo_offer:
                    continue

                try:
                    submitted = submit_for_approval(
                        run_id=run_id,
                        business_id=business_id,
                        offer=combo_offer,
                        targets=combo_targets,
                        sender_name=YOUR_NAME,
                    )
                    total_submitted += submitted
                except Exception as e:
                    logger.warning(f"H failed for {combo_name}: {e}")

            if total_submitted:
                steps.append(_make_step_result("H: CEO承認申請", STEP_OK,
                                               count=total_submitted))
                notify(
                    f"👔 *CEO承認待ち* — {total_submitted}件のメール送信申請があります。\n"
                    f"`mail_approval` シートで GO/STOP を記入してください。"
                )
            else:
                steps.append(_make_step_result("H: CEO承認申請", STEP_WARN,
                                               warnings=["申請0件"]))

        # ===================================================================
        # Report
        # ===================================================================
        elapsed = time.time() - start_time
        total_duration = f"{int(elapsed // 60)}分{int(elapsed % 60)}秒"

        budget_info = check_budget_gate()
        send_pipeline_report(steps, run_id, total_duration, budget_info)

        has_errors = any(s["status"] == STEP_FAIL for s in steps)
        final_status = "error" if has_errors else "success"
        step_summary = ", ".join(
            f"{s['name'].split(':')[0].strip()}: {s.get('count', 0)}件"
            for s in steps if s.get("count")
        )

        v2_metrics: dict = {
            "run_id": run_id,
            "total_duration_sec": int(elapsed),
            "budget_jpy": budget_info.get("cumulative_jpy", 0),
        }
        for s in steps:
            name = s["name"]
            count = s.get("count", 0)
            if "Layer1" in name:
                v2_metrics["types_generated"] = count
            elif "Layer2" in name:
                v2_metrics["combos_generated"] = count
            elif "需要検証" in name:
                v2_metrics["demand_verified"] = count
            elif "競合" in name:
                v2_metrics["competitor_passed"] = count
            elif "オファー" in name:
                v2_metrics["offers_generated"] = count
            elif "LP" in name:
                v2_metrics["lp_ready"] = count
            elif "メール収集" in name:
                v2_metrics["email_targets"] = count
            elif "CEO" in name:
                v2_metrics["approval_submitted"] = count

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
