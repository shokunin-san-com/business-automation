"""
0_idea_generator.py — V2: Instant-decision offer generation (3 offers).

Reads gap_top3 from competitor_20_log, generates 3 offers
with 7 mandatory fields each. Outputs to offer_3_log sheet.

All scoring (ceo_fit_score etc.) is **prohibited**.
Format deficiency → up to 3 retries. 3 failures → error stop.

Schedule: triggered by orchestrate_v2.py after competitor analysis
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import TEMPLATES_DIR, DATA_DIR, get_logger
from utils.claude_client import generate_json_with_retry
from utils.sheets_client import get_all_rows, append_rows
from utils.slack_notifier import send_message as slack_notify
from utils.status_writer import update_status
from utils.pdf_knowledge import get_knowledge_summary
from utils.learning_engine import get_learning_context
from utils.validators import validate_offer_3

logger = get_logger("idea_generator", "idea_generator.log")
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_settings() -> dict:
    rows = get_all_rows("settings")
    return {r["key"]: r["value"] for r in rows}


def _get_competitor_data(run_id: str | None = None) -> tuple[list[dict], list[dict], str]:
    """Get competitor data and gap_top3 from competitor_20_log.

    Returns: (competitors, gap_top3, market_name)
    """
    try:
        rows = get_all_rows("competitor_20_log")
        if run_id:
            rows = [r for r in rows if r.get("run_id") == run_id]
        if not rows:
            return [], [], ""

        market_name = rows[0].get("market", "")
        return rows, [], market_name  # gap_top3 is stored separately
    except Exception:
        return [], [], ""


def _get_gate_result(run_id: str | None = None) -> dict:
    """Get gate result with payer info for the offer prompt context."""
    try:
        rows = get_all_rows("gate_decision_log")
        if run_id:
            rows = [r for r in rows if r.get("run_id") == run_id]
        pass_rows = [r for r in rows if r.get("status") == "PASS"]
        if pass_rows:
            return pass_rows[-1]
    except Exception:
        pass
    return {}


def _already_generated(run_id: str) -> bool:
    """Check if offers already exist for this run."""
    try:
        rows = get_all_rows("offer_3_log")
        return any(r.get("run_id") == run_id for r in rows)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Core offer generation
# ---------------------------------------------------------------------------

def generate_offers(
    gap_top3: list[dict],
    gate_result: dict,
    micro_market: dict,
    knowledge_context: str,
    learning_context: str,
    run_id: str,
) -> list[dict]:
    """Generate 3 instant-decision offers from gap analysis.

    Uses generate_json_with_retry with validate_offer_3.
    3 retries max — 3 failures = error stop (do NOT proceed with incomplete data).
    """
    template = jinja_env.get_template("offer_3_prompt.j2")
    prompt = template.render(
        micro_market_json=json.dumps(micro_market, ensure_ascii=False),
        gap_top3_json=json.dumps(gap_top3, ensure_ascii=False),
        gate_result_json=json.dumps(gate_result, ensure_ascii=False),
        knowledge_context=knowledge_context,
        learning_context=learning_context,
    )

    result = generate_json_with_retry(
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

    if isinstance(result, dict):
        result = [result]

    # Strict check: if validation still fails after 3 retries, error stop
    vr = validate_offer_3(result)
    if not vr.valid:
        raise ValueError(
            f"オファー生成が3回リトライ後も不完全です。"
            f"エラー: {vr.errors}。不完全なまま進めません。"
        )

    return result


def save_offers_to_sheets(offers: list[dict], run_id: str) -> int:
    """Save 3 offers to offer_3_log sheet."""
    rows: list[list] = []

    for offer in offers:
        rows.append([
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

    if rows:
        append_rows("offer_3_log", rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main(run_id: str | None = None):
    """
    V2 Offer Generator: 3 instant-decision offers from competitor gaps.

    Can be called standalone or from orchestrate_v2.py with a shared run_id.
    """
    logger.info("=== V2 Offer generator start ===")
    update_status("0_idea_generator", "running", "V2オファー生成を開始...")

    try:
        knowledge_context = get_knowledge_summary()
        learning_context = get_learning_context(categories=["idea_generation"])

        # Get competitor data for this run
        competitors, _, market_name = _get_competitor_data(run_id)
        if not competitors:
            msg = "competitor_20_logにデータなし。競合分析が先に必要です"
            logger.info(msg)
            update_status("0_idea_generator", "success", msg,
                          {"offers_generated": 0})
            return {"offers": []}

        effective_run_id = run_id or competitors[0].get("run_id", "")

        # Skip if already generated
        if effective_run_id and _already_generated(effective_run_id):
            msg = f"run_id={effective_run_id[:8]} はオファー生成済み。スキップ"
            logger.info(msg)
            update_status("0_idea_generator", "success", msg)
            return {"offers": []}

        # Get gap_top3 — this was stored in orchestrate_v2 context
        # or we need to parse from competitor analysis result
        # For standalone execution, we reconstruct from competitors
        gap_top3 = _extract_gap_top3_from_context(effective_run_id, competitors)

        # Get gate result for payer info
        gate_result = _get_gate_result(effective_run_id)

        micro_market = {
            "micro_market": market_name,
            "payer": gate_result.get("payer", ""),
        }

        logger.info(f"Generating 3 offers for: {market_name}")
        update_status("0_idea_generator", "running", f"オファー3案生成中: {market_name}")

        # Generate offers
        offers = generate_offers(
            gap_top3, gate_result, micro_market,
            knowledge_context, learning_context,
            effective_run_id,
        )

        # Save to sheets
        count = save_offers_to_sheets(offers, effective_run_id)

        offer_names = " / ".join(
            o.get("offer_name", "")[:20] for o in offers[:3]
        )

        if count > 0:
            slack_notify(
                f":bulb: V2オファー生成完了: *{market_name}*\n"
                f"  {count}案: {offer_names}"
            )

        update_status(
            "0_idea_generator", "success",
            f"{count}案生成: {offer_names}",
            {
                "run_id": effective_run_id,
                "offers_generated": count,
            },
        )

        logger.info(f"=== V2 Offer generator complete: {count} offers ===")

        return {
            "run_id": effective_run_id,
            "market_name": market_name,
            "offers": offers,
        }

    except Exception as e:
        update_status("0_idea_generator", "error", str(e))
        logger.error(f"V2 Offer generator failed: {e}")
        raise


def _extract_gap_top3_from_context(
    run_id: str,
    competitors: list[dict],
) -> list[dict]:
    """Extract gap_top3 from available data.

    When called from orchestrate_v2, gap_top3 is passed directly.
    For standalone execution, we create a minimal gap list from
    competitor data patterns.
    """
    # Try to get from orchestrate_v2 context (stored as a temp file)
    gap_file = DATA_DIR / f"gap_top3_{run_id}.json"
    if gap_file.exists():
        try:
            return json.loads(gap_file.read_text("utf-8"))
        except (json.JSONDecodeError, IOError):
            pass

    # Fallback: generate basic gap context from competitor patterns
    # This is a simplified version — the full gap_top3 comes from competitor_20_prompt.j2
    logger.warning(
        "gap_top3 not found in context. Using empty gaps — "
        "offer generation may be suboptimal."
    )
    return [
        {"rank": 1, "gap": "競合データからのギャップ分析が必要", "evidence_url": "", "evidence_description": ""},
        {"rank": 2, "gap": "追加調査が必要", "evidence_url": "", "evidence_description": ""},
        {"rank": 3, "gap": "追加調査が必要", "evidence_url": "", "evidence_description": ""},
    ]


if __name__ == "__main__":
    main()
