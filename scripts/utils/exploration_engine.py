"""
exploration_engine.py — 3-Layer business model exploration.

Layer 1: AI generates 100+ business model "types" across 3 rounds.
         Types are broad categories like 業務代行, アフィリエイト, 送客, マッチング, etc.

Layer 2: Cross each type with construction industry needs to produce
         5-15 concrete business combos per type.

Called by orchestrate_v2.py in Phase A and Phase B.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TEMPLATES_DIR, get_logger
from utils.claude_client import generate_json_with_retry
from utils.sheets_client import append_rows, ensure_sheet_exists

logger = get_logger("exploration_engine", "exploration_engine.log")
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

# Sheet definitions
TYPES_SHEET = "business_model_types"
TYPES_HEADERS = [
    "type_id", "type_name", "description", "revenue_model",
    "example", "requires_license", "initial_investment",
    "round", "status", "run_id", "created_at",
]

COMBOS_SHEET = "business_combos"
COMBOS_HEADERS = [
    "combo_id", "type_id", "type_name", "business_name",
    "target", "deliverable", "price_model", "monthly_300_path",
    "demand_verdict", "status", "run_id", "created_at",
]


# ---------------------------------------------------------------------------
# CEO Constraint Loader
# ---------------------------------------------------------------------------

def load_ceo_constraints(settings: dict) -> dict:
    """Build CEO constraints dict from settings sheet.

    Reads ceo_* keys; JSON arrays are parsed automatically.
    Falls back to sensible defaults for missing keys.
    """
    def _parse_json_or_str(val: str) -> list | str:
        if not val:
            return []
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        return [v.strip() for v in val.split(",") if v.strip()]

    return {
        "industry": settings.get("ceo_industry", "建設業"),
        "channel": settings.get("ceo_channel", "Web完結"),
        "team": settings.get("ceo_team", "2-5人(開発/AI/営業/マーケ/コンサル)"),
        "budget": settings.get("ceo_budget", "初期投資ほぼゼロ"),
        "target_monthly_profit": int(settings.get("ceo_target_monthly_profit", "3000000")),
        "licenses": _parse_json_or_str(settings.get("ceo_licenses", "")),
        "experience": _parse_json_or_str(settings.get("ceo_experience", "")),
        "exclude": _parse_json_or_str(settings.get("ceo_exclude", "")),
    }


# ---------------------------------------------------------------------------
# Layer 1: Business Model Type Generation
# ---------------------------------------------------------------------------

def generate_business_model_types(
    ceo_constraints: dict,
    knowledge_context: str,
    run_id: str,
    round_num: int,
    existing_types: list[dict],
    target_per_round: int = 35,
) -> list[dict]:
    """Generate business model types for a single round.

    Returns list of type dicts: [{type_id, type_name, description,
    revenue_model, example, requires_license, initial_investment}]
    """
    template = jinja_env.get_template("layer1_type_gen_prompt.j2")

    existing_summary = ""
    if existing_types:
        lines = [f"- {t['type_name']}: {t['description']}" for t in existing_types]
        existing_summary = "\n".join(lines)

    prompt = template.render(
        ceo_industry=ceo_constraints["industry"],
        ceo_channel=ceo_constraints["channel"],
        ceo_team=ceo_constraints["team"],
        ceo_budget=ceo_constraints["budget"],
        ceo_target_monthly_profit=ceo_constraints["target_monthly_profit"],
        ceo_licenses_json=json.dumps(ceo_constraints["licenses"], ensure_ascii=False),
        ceo_experience_json=json.dumps(ceo_constraints["experience"], ensure_ascii=False),
        ceo_exclude_json=json.dumps(ceo_constraints["exclude"], ensure_ascii=False),
        knowledge_context=knowledge_context,
        round_num=round_num,
        existing_types_summary=existing_summary,
        target_count=target_per_round,
    )

    from utils.validators import validate_business_model_types

    result = generate_json_with_retry(
        prompt=prompt,
        system=(
            "あなたは建設業界に精通したビジネスアナリストです。"
            "ビジネスモデルの「型」を網羅的にリストアップしてください。"
            "必ずJSON配列で出力してください。"
        ),
        max_tokens=32768,
        temperature=0.6,
        max_retries=2,
        validator=validate_business_model_types,
    )

    if isinstance(result, dict):
        result = [result]

    # Assign type_ids
    offset = len(existing_types)
    for i, t in enumerate(result):
        t["type_id"] = f"BT-{offset + i + 1:03d}"

    logger.info(f"Layer 1 round {round_num}: generated {len(result)} types")
    return result


def self_review_types(types: list[dict], ceo_constraints: dict) -> list[dict]:
    """Rule-based filter to exclude infeasible types."""
    held_licenses = ceo_constraints.get("licenses", [])
    excludes = [e.lower() for e in ceo_constraints.get("exclude", [])]
    valid = []

    for t in types:
        desc = (t.get("description", "") + " " + t.get("example", "")).lower()
        name = t.get("type_name", "").lower()

        # Web完結 check
        if any(w in desc for w in ["対面営業が必須", "対面訪問必須", "現場常駐必須"]):
            logger.debug(f"除外(対面必須): {t.get('type_name')}")
            continue

        # Hardware / high investment check
        investment = str(t.get("initial_investment", "")).lower()
        if any(w in investment for w in ["100万以上", "数百万", "1000万", "高い"]):
            logger.debug(f"除外(初期投資大): {t.get('type_name')}")
            continue
        if any(w in desc for w in ["ドローン", "iot", "センサー", "3dプリンタ", "bim開発"]):
            logger.debug(f"除外(ハードウェア): {t.get('type_name')}")
            continue

        # License check
        required = str(t.get("requires_license", "")).strip()
        if required and required.lower() not in ("なし", "不要", "false", ""):
            if not any(lic in required for lic in held_licenses):
                logger.debug(f"除外(許認可なし): {t.get('type_name')} - 必要: {required}")
                continue

        # Exclusion keyword check
        if any(exc in name or exc in desc for exc in excludes if len(exc) > 2):
            logger.debug(f"除外(除外KW): {t.get('type_name')}")
            continue

        valid.append(t)

    excluded = len(types) - len(valid)
    if excluded:
        logger.info(f"セルフレビュー: {len(types)}型 → {len(valid)}型 (除外: {excluded}型)")
    return valid


def _deduplicate_types(types: list[dict]) -> list[dict]:
    """Remove duplicate types by normalized name."""
    seen = set()
    unique = []
    for t in types:
        key = t.get("type_name", "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(t)
    return unique


def _save_types_to_sheet(
    types: list[dict], run_id: str, round_num: int
) -> int:
    """Write types to business_model_types sheet."""
    ensure_sheet_exists(TYPES_SHEET, TYPES_HEADERS)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    for t in types:
        rows.append([
            t.get("type_id", ""),
            t.get("type_name", ""),
            t.get("description", ""),
            t.get("revenue_model", ""),
            t.get("example", ""),
            str(t.get("requires_license", "")),
            str(t.get("initial_investment", "")),
            str(round_num),
            "active",
            run_id,
            now,
        ])
    if rows:
        append_rows(TYPES_SHEET, rows)
    return len(rows)


def run_layer1(
    ceo_constraints: dict,
    knowledge_context: str,
    run_id: str,
    rounds: int = 3,
    target_per_round: int = 35,
) -> list[dict]:
    """Run all rounds of Layer 1, accumulating and deduplicating types.

    Returns the full deduplicated and reviewed list.
    """
    all_types: list[dict] = []

    for rnd in range(1, rounds + 1):
        logger.info(f"=== Layer 1 Round {rnd}/{rounds} ===")

        new_types = generate_business_model_types(
            ceo_constraints=ceo_constraints,
            knowledge_context=knowledge_context,
            run_id=run_id,
            round_num=rnd,
            existing_types=all_types,
            target_per_round=target_per_round,
        )

        # Self-review (rule-based filter)
        new_types = self_review_types(new_types, ceo_constraints)

        # Save this round to sheet
        saved = _save_types_to_sheet(new_types, run_id, rnd)
        logger.info(f"Round {rnd}: {saved}型保存")

        all_types.extend(new_types)

        # Rate limit between rounds
        if rnd < rounds:
            time.sleep(2.0)

    # Final dedup across all rounds
    all_types = _deduplicate_types(all_types)

    # Re-index type_ids after dedup
    for i, t in enumerate(all_types):
        t["type_id"] = f"BT-{i + 1:03d}"

    logger.info(f"Layer 1 complete: {len(all_types)}型 (全{rounds}ラウンド)")
    return all_types


# ---------------------------------------------------------------------------
# Layer 2: Type x Needs Combo Generation
# ---------------------------------------------------------------------------

def generate_combos_for_type(
    business_type: dict,
    ceo_constraints: dict,
    knowledge_context: str,
    run_id: str,
) -> list[dict]:
    """Cross a single business model type with construction industry needs.

    Returns 5-15 combo dicts.
    """
    template = jinja_env.get_template("layer2_combo_gen_prompt.j2")

    prompt = template.render(
        business_type_json=json.dumps(business_type, ensure_ascii=False),
        ceo_constraints_json=json.dumps(ceo_constraints, ensure_ascii=False),
        knowledge_context=knowledge_context,
    )

    from utils.validators import validate_business_combos

    result = generate_json_with_retry(
        prompt=prompt,
        system=(
            "あなたは建設業界のビジネスコンサルタントです。"
            "指定されたビジネスモデルの型を建設業のニーズと掛け合わせ、"
            "具体的なビジネスアイデアをJSON配列で出力してください。"
        ),
        max_tokens=16384,
        temperature=0.5,
        max_retries=2,
        validator=validate_business_combos,
    )

    if isinstance(result, dict):
        result = [result]

    # Inject type reference
    for c in result:
        c["type_id"] = business_type.get("type_id", "")
        c["type_name"] = business_type.get("type_name", "")

    return result


def self_review_combos(combos: list[dict], ceo_constraints: dict) -> list[dict]:
    """Rule-based filter for combos."""
    valid = []
    for c in combos:
        name = (c.get("business_name", "") + " " + c.get("deliverable", "")).lower()

        # SaaS / platform development exclusion
        if any(w in name for w in ["saas開発", "アプリ開発", "プラットフォーム開発", "システム構築"]):
            continue

        # Hardware exclusion
        if any(w in name for w in ["ドローン", "iot", "センサー", "3d", "bim"]):
            continue

        # Non-web exclusion
        if any(w in name for w in ["対面営業", "訪問営業", "展示会出展"]):
            continue

        valid.append(c)

    excluded = len(combos) - len(valid)
    if excluded:
        logger.debug(f"コンボ除外: {excluded}件")
    return valid


def _save_combos_to_sheet(combos: list[dict], run_id: str) -> int:
    """Write combos to business_combos sheet."""
    ensure_sheet_exists(COMBOS_SHEET, COMBOS_HEADERS)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    for c in combos:
        rows.append([
            c.get("combo_id", ""),
            c.get("type_id", ""),
            c.get("type_name", ""),
            c.get("business_name", ""),
            c.get("target", ""),
            c.get("deliverable", ""),
            c.get("price_model", ""),
            c.get("monthly_300_path", ""),
            c.get("demand_verdict", "pending"),
            "pending",
            run_id,
            now,
        ])
    if rows:
        append_rows(COMBOS_SHEET, rows)
    return len(rows)


def run_layer2(
    types: list[dict],
    ceo_constraints: dict,
    knowledge_context: str,
    run_id: str,
    batch_size: int = 5,
) -> list[dict]:
    """Run Layer 2 across all types.

    Processes types in batches and saves after each batch.
    Returns full combo list.
    """
    all_combos: list[dict] = []
    combo_counter = 0

    for i in range(0, len(types), batch_size):
        batch = types[i:i + batch_size]
        batch_combos: list[dict] = []

        for btype in batch:
            logger.info(f"Layer 2: {btype['type_name']} (BT-{btype.get('type_id', '?')})")
            try:
                combos = generate_combos_for_type(
                    business_type=btype,
                    ceo_constraints=ceo_constraints,
                    knowledge_context=knowledge_context,
                    run_id=run_id,
                )
                combos = self_review_combos(combos, ceo_constraints)

                # Assign combo_ids
                for c in combos:
                    combo_counter += 1
                    c["combo_id"] = f"BC-{combo_counter:04d}"

                batch_combos.extend(combos)
                logger.info(f"  → {len(combos)} combos generated")
            except Exception as e:
                logger.warning(f"Layer 2 failed for {btype.get('type_name')}: {e}")
                continue

            time.sleep(1.0)  # Rate limit between types

        # Save batch to sheet
        if batch_combos:
            _save_combos_to_sheet(batch_combos, run_id)
            all_combos.extend(batch_combos)

        batch_num = (i // batch_size) + 1
        total_batches = (len(types) + batch_size - 1) // batch_size
        logger.info(
            f"Layer 2 batch {batch_num}/{total_batches}: "
            f"{len(batch_combos)} combos (累計: {len(all_combos)})"
        )

    logger.info(f"Layer 2 complete: {len(all_combos)} combos from {len(types)} types")
    return all_combos
