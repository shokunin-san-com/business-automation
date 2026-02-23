"""
A_market_research.py — V2: Evidence-based market gate pipeline.

Flow: A0 (micro-market generation) → A1q (quick gate) → A1d (deep gate) → Exploration lane check.

All scoring is **prohibited**. Every gate decision is PASS/FAIL based on evidence URLs.
Micro-market unit = industry × task × role × timing × regulation + intent word.

Schedule: Sunday 20:00 (weekly) — triggered by orchestrate_v2.py
"""
from __future__ import annotations

import json
import uuid
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import TEMPLATES_DIR, get_logger
from utils.claude_client import generate_json, generate_json_with_retry
from utils.sheets_client import get_all_rows, append_rows
from utils.slack_notifier import send_message as slack_notify
from utils.status_writer import update_status
from utils.pdf_knowledge import get_knowledge_summary
from utils.validators import validate_a1_quick, validate_a1_deep

logger = get_logger("market_research", "market_research.log")
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


# ---------------------------------------------------------------------------
# Settings helper
# ---------------------------------------------------------------------------

def _load_settings() -> dict:
    rows = get_all_rows("settings")
    return {r["key"]: r["value"] for r in rows}


# ---------------------------------------------------------------------------
# A0: Micro-market generation
# ---------------------------------------------------------------------------

def step_a0_generate_micro_markets(
    settings: dict,
    knowledge_context: str,
    run_id: str,
) -> list[dict]:
    """
    Generate 30-50 micro-markets from exploration_markets.

    Rules:
    - Unit: industry × task × role × timing × regulation + intent_word
    - Stop condition: max 50 or last 10 contain 7+ same industry×task pattern
    - Saves results to micro_market_list sheet (with run_id)
    """
    exploration_markets = settings.get(
        "exploration_markets",
        settings.get("target_industries", "IT,エネルギー"),
    )
    market_direction_notes = settings.get("market_direction_notes", "")

    # Fetch existing micro-markets to avoid duplicates
    existing_mm: list[str] = []
    try:
        existing_rows = get_all_rows("micro_market_list")
        existing_mm = [
            r.get("micro_market", "") for r in existing_rows
            if r.get("micro_market")
        ]
    except Exception:
        pass

    template = jinja_env.get_template("micro_market_gen_prompt.j2")
    prompt = template.render(
        exploration_markets=exploration_markets,
        market_direction_notes=market_direction_notes,
        knowledge_context=knowledge_context,
        existing_micro_markets=json.dumps(existing_mm[-100:], ensure_ascii=False) if existing_mm else "",
        target_count=40,
        max_count=50,
    )

    result = generate_json(
        prompt=prompt,
        system=(
            "あなたは日本市場に精通したマイクロ市場設計の専門家です。"
            "スコアを出すな。推定値でPASSするな。架空のURLは絶対に出すな。"
            "必ず指定のJSON配列フォーマットで出力してください。"
        ),
        max_tokens=16384,
        temperature=0.6,
    )

    if isinstance(result, dict):
        result = [result]

    # Validate and cap at 50
    result = result[:50]

    # Apply stop condition: if last 10 have 7+ same industry×task, truncate
    if len(result) > 10:
        last_10 = result[-10:]
        patterns = [f"{m.get('industry', '')}×{m.get('task', '')}" for m in last_10]
        top_pattern_count = Counter(patterns).most_common(1)[0][1] if patterns else 0
        if top_pattern_count >= 7:
            # Find where repetition started and truncate
            top_pattern = Counter(patterns).most_common(1)[0][0]
            for i in range(len(result) - 10, len(result)):
                p = f"{result[i].get('industry', '')}×{result[i].get('task', '')}"
                if p == top_pattern:
                    result = result[:i]
                    logger.info(f"A0: Stopped early at {len(result)} markets (repetition detected)")
                    break

    # Save to micro_market_list sheet
    rows: list[list] = []
    for idx, m in enumerate(result, 1):
        market_id = m.get("market_id", f"MM-{idx:03d}")
        rows.append([
            run_id,
            market_id,
            m.get("micro_market", ""),
            m.get("industry", ""),
            m.get("task", ""),
            m.get("role", ""),
            m.get("timing", ""),
            m.get("regulation", ""),
            m.get("intent_word", ""),
            "pending",  # a1q_status
        ])

    if rows:
        append_rows("micro_market_list", rows)
        logger.info(f"A0: Saved {len(rows)} micro-markets to sheet")

    return result


# ---------------------------------------------------------------------------
# A1q: Quick gate (shallow evidence check)
# ---------------------------------------------------------------------------

def step_a1_quick_gate(
    micro_markets: list[dict],
    knowledge_context: str,
    run_id: str,
) -> tuple[list[dict], list[dict]]:
    """
    Apply shallow gate to all micro-markets.

    Requirements per market:
    - Payment evidence URL (>=1)
    - At least 1 category (demand/seriousness/tailwind) with value + URL

    Returns: (passed_list, full_results_for_log)
    """
    template = jinja_env.get_template("a1_quick_gate_prompt.j2")
    prompt = template.render(
        micro_markets_json=json.dumps(micro_markets, ensure_ascii=False),
        knowledge_context=knowledge_context,
    )

    result = generate_json_with_retry(
        prompt=prompt,
        system=(
            "あなたは市場参入判定の専門家です。"
            "スコアを出すな。推定値でPASSするな。架空のURLは絶対に出すな。"
            "判定はPASS/FAILの2値のみ。条件付きPASSは禁止。"
            "必ず指定のJSON配列フォーマットで出力してください。"
        ),
        max_tokens=16384,
        temperature=0.3,
        max_retries=2,
        validator=validate_a1_quick,
    )

    if isinstance(result, dict):
        result = [result]

    passed = [r for r in result if r.get("status") == "PASS"]
    failed = [r for r in result if r.get("status") != "PASS"]

    logger.info(f"A1q: {len(passed)} PASS / {len(failed)} FAIL out of {len(result)}")

    return passed, result


# ---------------------------------------------------------------------------
# A1d: Deep gate (full 8-condition evidence check)
# ---------------------------------------------------------------------------

def step_a1_deep_gate(
    passed_markets: list[dict],
    settings: dict,
    knowledge_context: str,
    run_id: str,
) -> tuple[list[dict], list[list]]:
    """
    Apply deep gate to top 5 PASS markets from A1q.

    All 8 conditions (a-h) must be met with evidence URLs:
    a: Payer identification (department + role)
    b: Price evidence (3 price URLs or 5 quote URLs or 3 cases + 2 quotes)
    c: Tailwind URLs (2+)
    d: Seriousness URLs (2+)
    e: Search metrics (2 of: volume, CPC, trend)
    f: Competitor URLs (10+ with real names + URLs)
    g: 3 gaps with evidence URLs
    h: 10-company profitability hypothesis

    Returns: (gate_results, gate_decision_log_rows)
    """
    # Limit to top 5
    targets = passed_markets[:5]
    gate_results: list[dict] = []
    gate_log_rows: list[list] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    template = jinja_env.get_template("a1_deep_gate_prompt.j2")

    for market in targets:
        market_name = market.get("micro_market", market.get("market_id", "unknown"))
        logger.info(f"A1d: Deep gate for {market_name}")
        update_status("A_market_research", "running", f"A1d: {market_name}")

        # Build a1_quick_result for context
        a1q_result = json.dumps(market, ensure_ascii=False)

        # For micro_market_json, include all available data
        micro_market_data = {
            "micro_market": market.get("micro_market", ""),
            "market_id": market.get("market_id", ""),
            "industry": market.get("industry", ""),
            "task": market.get("task", ""),
            "role": market.get("role", ""),
            "timing": market.get("timing", ""),
            "regulation": market.get("regulation", ""),
            "intent_word": market.get("intent_word", ""),
        }

        prompt = template.render(
            micro_market_json=json.dumps(micro_market_data, ensure_ascii=False),
            a1_quick_result_json=a1q_result,
            knowledge_context=knowledge_context,
        )

        result = generate_json_with_retry(
            prompt=prompt,
            system=(
                "あなたは市場参入判定の専門家です。"
                "スコアを出すな。推定値でPASSするな。架空のURLは絶対に出すな。"
                "全8条件クリアでPASS。1つでも欠けたらFAIL。"
                "必ず指定のJSONオブジェクトフォーマットで出力してください。"
            ),
            max_tokens=16384,
            temperature=0.3,
            max_retries=2,
            validator=validate_a1_deep,
        )

        if isinstance(result, list):
            result = result[0] if result else {"status": "FAIL", "missing_items": ["APIエラー"]}

        gate_results.append(result)

        # Build gate_decision_log row
        status = result.get("status", "FAIL")
        missing = result.get("missing_items", [])
        evidence_urls = result.get("evidence_urls_all", [])
        conditions = result.get("conditions", {})
        payer_info = ""
        blackout = ""
        if conditions:
            a_payer = conditions.get("a_payer", {})
            payer_info = f"{a_payer.get('department', '')} {a_payer.get('role', '')}"
            h_hyp = conditions.get("h_blackout_hypothesis", {})
            blackout = h_hyp.get("profit_narrative", "")

        gate_log_rows.append([
            run_id,
            now,
            market_name,
            status,
            json.dumps(missing, ensure_ascii=False),
            json.dumps(evidence_urls[:50], ensure_ascii=False),  # cap URL list
            payer_info,
            blackout,
        ])

        logger.info(f"A1d: {market_name} => {status} (missing: {missing})")

    # Save gate_decision_log
    if gate_log_rows:
        append_rows("gate_decision_log", gate_log_rows)
        logger.info(f"A1d: Saved {len(gate_log_rows)} gate decisions to sheet")

    return gate_results, gate_log_rows


# ---------------------------------------------------------------------------
# Exploration lane check
# ---------------------------------------------------------------------------

def check_exploration_lane(
    failed_results: list[dict],
    run_id: str,
) -> dict | None:
    """
    Check if any FAIL market qualifies for exploration lane.

    Conditions:
    - Payer identified (condition a met)
    - Urgent pain that can't be postponed
    - Potential for 5 interviews within 7 days
    - Max 1 active exploration lane at a time

    Returns the qualifying market dict or None.
    """
    # Check if there's already an active exploration lane
    try:
        existing_lanes = get_all_rows("exploration_lane_log")
        active_lanes = [
            l for l in existing_lanes
            if l.get("status") == "ACTIVE"
        ]
        if active_lanes:
            logger.info("Exploration lane: Already 1 ACTIVE lane — skipping")
            return None
    except Exception:
        pass

    for result in failed_results:
        if result.get("status") == "PASS":
            continue  # Skip passed markets

        conditions = result.get("conditions", {})
        a_payer = conditions.get("a_payer", {})

        # Must have payer identified
        if not a_payer.get("met", False):
            continue

        # Check if this market has potential for exploration
        # payer identified + at least 2 other conditions met (showing partial viability)
        missing = result.get("missing_items", [])
        met_count = sum(1 for c in conditions.values() if isinstance(c, dict) and c.get("met", False))

        if met_count >= 3:
            market_name = result.get("micro_market", "unknown")
            now = datetime.now()
            deadline = (now + timedelta(days=7)).strftime("%Y-%m-%d")

            # Save to exploration_lane_log
            append_rows("exploration_lane_log", [[
                run_id,
                market_name,
                f"支払者特定済み + {met_count}/8条件クリア。ヒアリングで残り条件の証拠収集可能性あり",
                deadline,
                0,  # interview_count starts at 0
                "ACTIVE",
            ]])

            logger.info(
                f"Exploration lane: {market_name} adopted "
                f"(met {met_count}/8 conditions, deadline {deadline})"
            )

            return {
                "micro_market": market_name,
                "conditions": conditions,
                "deadline": deadline,
                "met_count": met_count,
            }

    logger.info("Exploration lane: No qualifying markets found")
    return None


# ---------------------------------------------------------------------------
# Settings snapshot
# ---------------------------------------------------------------------------

def save_settings_snapshot(settings: dict, run_id: str) -> None:
    """Save current settings as JSON snapshot for run reproducibility."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    append_rows("settings_snapshot", [[
        run_id,
        now,
        json.dumps(settings, ensure_ascii=False),
    ]])
    logger.info(f"Settings snapshot saved for run {run_id}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main(run_id: str | None = None):
    """
    V2 Market Research Pipeline: A0 -> A1q -> A1d -> Exploration Lane.

    Can be called standalone or from orchestrate_v2.py with a shared run_id.
    """
    if run_id is None:
        run_id = str(uuid.uuid4())

    logger.info(f"=== V2 Market Research start (run_id={run_id}) ===")
    update_status("A_market_research", "running", f"V2パイプライン開始 (run_id={run_id[:8]})")

    try:
        settings = _load_settings()
        knowledge_context = get_knowledge_summary()

        # Save settings snapshot
        save_settings_snapshot(settings, run_id)

        # ---------------------------------------------------------------
        # A0: Generate micro-markets
        # ---------------------------------------------------------------
        update_status("A_market_research", "running", "A0: マイクロ市場生成中...")
        micro_markets = step_a0_generate_micro_markets(settings, knowledge_context, run_id)

        if not micro_markets:
            msg = "A0: マイクロ市場生成に失敗しました（0件）"
            update_status("A_market_research", "error", msg)
            slack_notify(f":x: {msg}")
            raise RuntimeError(msg)

        logger.info(f"A0: Generated {len(micro_markets)} micro-markets")

        # ---------------------------------------------------------------
        # A1q: Quick gate
        # ---------------------------------------------------------------
        update_status("A_market_research", "running", f"A1q: {len(micro_markets)}市場を浅いゲート判定中...")
        a1q_passed, a1q_all = step_a1_quick_gate(micro_markets, knowledge_context, run_id)

        if not a1q_passed:
            msg = f"A1q: 全{len(micro_markets)}市場がFAIL。浅いゲートを通過した市場なし"
            update_status("A_market_research", "error", msg)
            slack_notify(f":x: {msg}")
            raise RuntimeError(msg)

        logger.info(f"A1q: {len(a1q_passed)} markets passed quick gate")

        # ---------------------------------------------------------------
        # A1d: Deep gate (max 5 markets)
        # ---------------------------------------------------------------
        update_status(
            "A_market_research", "running",
            f"A1d: {len(a1q_passed[:5])}市場を深いゲート判定中..."
        )
        a1d_results, gate_log = step_a1_deep_gate(
            a1q_passed, settings, knowledge_context, run_id
        )

        passed_markets = [r for r in a1d_results if r.get("status") == "PASS"]
        failed_markets = [r for r in a1d_results if r.get("status") != "PASS"]

        # ---------------------------------------------------------------
        # Exploration lane check (for FAIL markets)
        # ---------------------------------------------------------------
        exploration = None
        if failed_markets:
            exploration = check_exploration_lane(failed_markets, run_id)

        # ---------------------------------------------------------------
        # Summary
        # ---------------------------------------------------------------
        summary_parts = [
            f"A0: {len(micro_markets)}マイクロ市場生成",
            f"A1q: {len(a1q_passed)}/{len(micro_markets)} PASS",
            f"A1d: {len(passed_markets)}/{len(a1q_passed[:5])} PASS",
        ]
        if exploration:
            summary_parts.append(f"探索レーン: {exploration['micro_market']}")

        total_pass = len(passed_markets)
        has_exploration = exploration is not None

        if total_pass == 0 and not has_exploration:
            detail = " | ".join(summary_parts) + " | PASS市場なし＋探索レーンなし"
            update_status("A_market_research", "error", detail)
            slack_notify(
                f":x: 市場調査v2完了 — **全市場FAIL**\n"
                + "\n".join(f"  {s}" for s in summary_parts)
            )
            raise RuntimeError(detail)

        detail = " | ".join(summary_parts)
        update_status(
            "A_market_research", "success", detail,
            {
                "run_id": run_id,
                "a0_count": len(micro_markets),
                "a1q_pass": len(a1q_passed),
                "a1d_pass": total_pass,
                "exploration": bool(exploration),
            },
        )

        slack_notify(
            f":mag: 市場調査v2完了\n"
            + "\n".join(f"  {s}" for s in summary_parts)
            + (f"\n  :rocket: 探索レーン採用: {exploration['micro_market']}" if exploration else "")
        )

        logger.info(f"=== V2 Market Research complete: {detail} ===")

        return {
            "run_id": run_id,
            "micro_markets": micro_markets,
            "a1q_passed": a1q_passed,
            "a1d_results": a1d_results,
            "passed_markets": passed_markets,
            "exploration": exploration,
        }

    except Exception as e:
        if "FAIL" not in str(e) and "PASS" not in str(e):
            update_status("A_market_research", "error", str(e))
        logger.error(f"V2 Market research failed: {e}")
        raise


if __name__ == "__main__":
    main()
