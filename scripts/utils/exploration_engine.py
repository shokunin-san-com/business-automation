"""
exploration_engine.py — 5-axis 20-prompt business model exploration.

Layer 1: 5 axes × 4 prompts each = 20 prompts → ~200 raw types
         → AI merge/dedup → 50-80 unique types (merged_from tracked)

Layer 2: Cross each type with construction industry needs to produce
         5-15 concrete business combos per type (batch of 5 types).

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
from utils.sheets_client import append_rows

logger = get_logger("exploration_engine", "exploration_engine.log")
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

# ---------------------------------------------------------------------------
# Construction Industry Context (injected into all AI prompts)
# ---------------------------------------------------------------------------
CONSTRUCTION_CONTEXT = """
【建設業界の商慣習】
- 重層下請構造（元請→1次→2次→3次）。意思決定者は現場所長＋本社工事部長の二重構造
- 予算は「工事ごと」に組まれ、月額サブスクの概念が薄い。出来高払い＋手形90日が標準
- 職人は日給月給。雨天休業、季節変動あり。人材不足が最大の経営課題
- 主要法規制：建設業法（許可・経審）、労働安全衛生法、建設リサイクル法、入管法（特定技能）
- 金の動き：公共工事は年度末集中、民間は着工〜竣工1-2年。資金繰りが常に課題
- IT導入：ANDPAD/Photoruction等は大手に普及済み。中小は紙+Excel+LINE+FAXが現役
- 許認可ビジネス：有料職業紹介（建設は例外的に許可が必要）、特定技能、M&A登録支援
""".strip()

# ---------------------------------------------------------------------------
# 5-Axis Prompt Definitions (20 prompts)
# ---------------------------------------------------------------------------
AXIS_PROMPTS = [
    # Axis 1: Revenue model (4 prompts)
    {
        "axis_id": "A1", "axis_name": "収益モデル軸",
        "prompt_id": "P01", "target_count": 10,
        "focus_areas": "月額課金・サブスクリプション型。建設会社が毎月定額で利用するサービス。",
    },
    {
        "axis_id": "A1", "axis_name": "収益モデル軸",
        "prompt_id": "P02", "target_count": 10,
        "focus_areas": "成果報酬・コミッション型。採用成功、受注成功、コスト削減成功で課金。",
    },
    {
        "axis_id": "A1", "axis_name": "収益モデル軸",
        "prompt_id": "P03", "target_count": 10,
        "focus_areas": "仲介・マッチング手数料型。職人と会社、買い手と売り手、発注者と施工者を繋ぐ。",
    },
    {
        "axis_id": "A1", "axis_name": "収益モデル軸",
        "prompt_id": "P04", "target_count": 10,
        "focus_areas": "掲載料・広告収入・コンテンツ販売型。メディア、ディレクトリ、教材、テンプレート販売。",
    },
    # Axis 2: Customer (4 prompts)
    {
        "axis_id": "A2", "axis_name": "顧客軸",
        "prompt_id": "P05", "target_count": 10,
        "focus_areas": "建設会社・専門工事会社（従業員10-100人規模）向け。経営者・部長が支払者。",
    },
    {
        "axis_id": "A2", "axis_name": "顧客軸",
        "prompt_id": "P06", "target_count": 10,
        "focus_areas": "一人親方・個人事業主向け。月1-5万円の手軽なサービス。事務・集客・資金繰りの悩み。",
    },
    {
        "axis_id": "A2", "axis_name": "顧客軸",
        "prompt_id": "P07", "target_count": 10,
        "focus_areas": "発注者・施主（行政/不動産デベ/個人施主）向け。施工者選定、品質チェック、コスト管理。",
    },
    {
        "axis_id": "A2", "axis_name": "顧客軸",
        "prompt_id": "P08", "target_count": 10,
        "focus_areas": "資材メーカー・建機レンタル・サプライヤー向け。販路開拓、受発注最適化、在庫回転。",
    },
    # Axis 3: License utilization (4 prompts)
    {
        "axis_id": "A3", "axis_name": "許認可活用軸",
        "prompt_id": "P09", "target_count": 10,
        "focus_areas": "有料職業紹介事業 × 建設業。施工管理技士・職人の紹介、建設業界特化の人材紹介。",
    },
    {
        "axis_id": "A3", "axis_name": "許認可活用軸",
        "prompt_id": "P10", "target_count": 10,
        "focus_areas": "特定技能・登録支援機関 × 建設業。外国人材受入支援、生活支援、在留資格管理。",
    },
    {
        "axis_id": "A3", "axis_name": "許認可活用軸",
        "prompt_id": "P11", "target_count": 10,
        "focus_areas": "M&A登録支援機関 × 建設業。後継者不在の建設会社M&A仲介、事業承継コンサル。",
    },
    {
        "axis_id": "A3", "axis_name": "許認可活用軸",
        "prompt_id": "P12", "target_count": 10,
        "focus_areas": "複合許認可活用。有料職業紹介+特定技能+M&Aを組み合わせた複合サービス。",
    },
    # Axis 4: Value chain (4 prompts)
    {
        "axis_id": "A4", "axis_name": "バリューチェーン軸",
        "prompt_id": "P13", "target_count": 10,
        "focus_areas": "受注前工程：入札支援、見積作成、営業支援、集客・SEO、公共工事情報収集。",
    },
    {
        "axis_id": "A4", "axis_name": "バリューチェーン軸",
        "prompt_id": "P14", "target_count": 10,
        "focus_areas": "施工中工程：施工管理支援、安全管理、品質管理、写真管理、日報・報告書。",
    },
    {
        "axis_id": "A4", "axis_name": "バリューチェーン軸",
        "prompt_id": "P15", "target_count": 10,
        "focus_areas": "完了後工程：竣工検査支援、アフターメンテナンス、保証管理、顧客フォロー。",
    },
    {
        "axis_id": "A4", "axis_name": "バリューチェーン軸",
        "prompt_id": "P16", "target_count": 10,
        "focus_areas": "経営管理：人事労務（社保・給与）、財務（資金繰り・融資）、法務（契約・許可更新）、経審対策。",
    },
    # Axis 5: Competitor gap (4 prompts)
    {
        "axis_id": "A5", "axis_name": "競合隙間軸",
        "prompt_id": "P17", "target_count": 10,
        "focus_areas": "ANDPAD/SPIDERPLUS等の高額建設SaaSが手が届かない中小企業向けの代替サービス。",
    },
    {
        "axis_id": "A5", "axis_name": "競合隙間軸",
        "prompt_id": "P18", "target_count": 10,
        "focus_areas": "助太刀/CraftBank等の建設マッチングプラットフォームの隙間。対応できていないニッチ。",
    },
    {
        "axis_id": "A5", "axis_name": "競合隙間軸",
        "prompt_id": "P19", "target_count": 10,
        "focus_areas": "既存BPO/士業/コンサルが高すぎる or 対応が遅い領域。行政書士/社労士/税理士の代替。",
    },
    {
        "axis_id": "A5", "axis_name": "競合隙間軸",
        "prompt_id": "P20", "target_count": 10,
        "focus_areas": "建設テック未開拓領域。CCUS/インボイス/働き方改革/BIM義務化から生まれる新ニーズ。",
    },
]


# ---------------------------------------------------------------------------
# CEO Constraint Loader
# ---------------------------------------------------------------------------

def load_ceo_constraints(settings: dict) -> dict:
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
# Layer 1: 5-Axis × 20-Prompt Type Generation
# ---------------------------------------------------------------------------

def _generate_types_for_prompt(
    prompt_def: dict,
    ceo_constraints: dict,
    knowledge_context: str,
    existing_type_names: list[str],
) -> list[dict]:
    template = jinja_env.get_template("layer1_type_gen_prompt.j2")

    existing_str = ""
    if existing_type_names:
        existing_str = ", ".join(existing_type_names[-80:])

    prompt = template.render(
        axis_name=prompt_def["axis_name"],
        axis_id=prompt_def["axis_id"],
        prompt_id=prompt_def["prompt_id"],
        focus_areas=prompt_def["focus_areas"],
        ceo_constraints_json=json.dumps(ceo_constraints, ensure_ascii=False),
        knowledge_context=knowledge_context,
        existing_type_names=existing_str,
        target_count=prompt_def["target_count"],
        construction_context=CONSTRUCTION_CONTEXT,
    )

    from utils.validators import validate_business_model_types

    result = generate_json_with_retry(
        prompt=prompt,
        system=(
            "あなたは建設業界に精通したビジネスアナリストです。"
            "ビジネスモデルの「型」をJSON配列で出力してください。"
        ),
        max_tokens=16384,
        temperature=0.6,
        max_retries=2,
        validator=validate_business_model_types,
    )

    if isinstance(result, dict):
        result = [result]

    for t in result:
        t["axis"] = prompt_def["axis_id"]
        t["prompt_id"] = prompt_def["prompt_id"]
        t["merged_from"] = []

    return result


def _self_review_types(types: list[dict], ceo_constraints: dict) -> list[dict]:
    held_licenses = ceo_constraints.get("licenses", [])
    excludes = [e.lower() for e in ceo_constraints.get("exclude", [])]
    valid = []

    for t in types:
        desc = (t.get("description", "") + " " + t.get("example", "")).lower()
        name = t.get("type_name", "").lower()

        if any(w in desc for w in ["対面営業が必須", "対面訪問必須", "現場常駐必須"]):
            continue
        if any(w in desc for w in ["ドローン", "iot", "センサー", "3dプリンタ", "bim開発"]):
            continue
        if any(w in name for w in ["saas", "プラットフォーム開発", "アプリ開発"]):
            continue
        if any(exc in name or exc in desc for exc in excludes if len(exc) > 2):
            continue

        valid.append(t)

    excluded = len(types) - len(valid)
    if excluded:
        logger.info(f"セルフレビュー: {len(types)}型 → {len(valid)}型 (除外: {excluded}型)")
    return valid


def _ai_merge_types(raw_types: list[dict]) -> list[dict]:
    template = jinja_env.get_template("layer1_merge_prompt.j2")

    types_for_merge = [
        {
            "type_name": t["type_name"],
            "description": t.get("description", ""),
            "revenue_model": t.get("revenue_model", ""),
            "example": t.get("example", ""),
            "axis": t.get("axis", ""),
            "prompt_id": t.get("prompt_id", ""),
        }
        for t in raw_types
    ]

    prompt = template.render(
        all_types_json=json.dumps(types_for_merge, ensure_ascii=False),
        target_range="50-80",
    )

    result = generate_json_with_retry(
        prompt=prompt,
        system=(
            "あなたはビジネス分類の専門家です。"
            "重複する型を統合し、merged_fromで追跡してください。"
            "必ずJSON配列で出力してください。"
        ),
        max_tokens=32768,
        temperature=0.3,
        max_retries=2,
    )

    if isinstance(result, dict):
        result = [result]

    for t in result:
        if "merged_from" not in t:
            t["merged_from"] = []

    logger.info(f"AI統合: {len(raw_types)}型 → {len(result)}型")
    return result


def _save_types_to_sheet(types: list[dict], run_id: str) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    for t in types:
        merged = t.get("merged_from", [])
        merged_str = json.dumps(merged, ensure_ascii=False) if merged else ""
        rows.append([
            run_id,
            t.get("type_id", ""),
            t.get("axis", ""),
            t.get("prompt_id", ""),
            t.get("type_name", ""),
            t.get("description", ""),
            t.get("revenue_model", ""),
            t.get("example", ""),
            merged_str,
            str(t.get("review_pass", "")),
            str(t.get("exists_check", "")),
            t.get("strength_fit", ""),
            now,
        ])
    if rows:
        append_rows("business_model_types", rows)
    return len(rows)


def _priority_sort(types: list[dict], ceo_constraints: dict) -> list[dict]:
    licenses = [l.lower() for l in ceo_constraints.get("licenses", [])]
    experience = " ".join(ceo_constraints.get("experience", [])).lower()

    def _score(t):
        desc = (t.get("description", "") + " " + t.get("example", "")).lower()
        name = t.get("type_name", "").lower()
        s = 0
        if any(lic in desc or lic in name for lic in licenses):
            s += 100
        if t.get("axis") == "A3":
            s += 50
        exp_kw = ["m&a", "建設", "施工", "海外", "人材紹介", "エネルギー"]
        if any(kw in desc or kw in name for kw in exp_kw if kw in experience):
            s += 30
        return s

    return sorted(types, key=_score, reverse=True)


def run_layer1(
    ceo_constraints: dict,
    knowledge_context: str,
    run_id: str,
) -> list[dict]:
    all_raw: list[dict] = []
    existing_names: list[str] = []

    for i, pdef in enumerate(AXIS_PROMPTS):
        pid = pdef["prompt_id"]
        logger.info(
            f"=== Layer 1 [{i+1}/{len(AXIS_PROMPTS)}] "
            f"{pdef['axis_name']} {pid} ==="
        )

        try:
            new_types = _generate_types_for_prompt(
                prompt_def=pdef,
                ceo_constraints=ceo_constraints,
                knowledge_context=knowledge_context,
                existing_type_names=existing_names,
            )
            new_types = _self_review_types(new_types, ceo_constraints)
            all_raw.extend(new_types)
            existing_names.extend(t["type_name"] for t in new_types)
            logger.info(f"  → {len(new_types)}型 (累計: {len(all_raw)})")
        except Exception as e:
            logger.warning(f"Prompt {pid} failed: {e}")
            continue

        try:
            from utils.cost_tracker import record_api_call
            record_api_call(
                run_id=run_id, phase="A_layer1",
                input_tokens=2000, output_tokens=4000,
                note=f"prompt={pid}",
            )
        except Exception:
            pass

        if i < len(AXIS_PROMPTS) - 1:
            time.sleep(1.5)

    logger.info(f"Layer 1 raw: {len(all_raw)}型 → AI統合開始")

    # AI merge/dedup
    merged = _ai_merge_types(all_raw)
    merged = _priority_sort(merged, ceo_constraints)

    # Assign type_ids
    for i, t in enumerate(merged):
        t["type_id"] = f"BT-{i + 1:03d}"

    # Save to sheet
    saved = _save_types_to_sheet(merged, run_id)
    logger.info(f"Layer 1 complete: {saved}型保存")

    return merged


# ---------------------------------------------------------------------------
# Layer 2: Type x Needs Combo Generation
# ---------------------------------------------------------------------------

def generate_combos_for_type(
    business_type: dict,
    ceo_constraints: dict,
    knowledge_context: str,
    run_id: str,
) -> list[dict]:
    template = jinja_env.get_template("layer2_combo_gen_prompt.j2")

    prompt = template.render(
        business_type_json=json.dumps(business_type, ensure_ascii=False),
        ceo_constraints_json=json.dumps(ceo_constraints, ensure_ascii=False),
        knowledge_context=knowledge_context,
        construction_context=CONSTRUCTION_CONTEXT,
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

    for c in result:
        c["type_id"] = business_type.get("type_id", "")
        c["type_name"] = business_type.get("type_name", "")

    return result


def _self_review_combos(combos: list[dict], ceo_constraints: dict) -> list[dict]:
    valid = []
    for c in combos:
        name = (c.get("business_name", "") + " " + c.get("deliverable", "")).lower()

        if any(w in name for w in ["saas開発", "アプリ開発", "プラットフォーム開発", "システム構築"]):
            continue
        if any(w in name for w in ["ドローン", "iot", "センサー", "3d", "bim"]):
            continue
        if any(w in name for w in ["対面営業", "訪問営業", "展示会出展"]):
            continue

        valid.append(c)

    excluded = len(combos) - len(valid)
    if excluded:
        logger.debug(f"コンボ除外: {excluded}件")
    return valid


def _save_combos_to_sheet(combos: list[dict], run_id: str) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    for c in combos:
        rows.append([
            run_id,
            c.get("combo_id", ""),
            c.get("type_id", ""),
            c.get("business_name", ""),
            c.get("target", ""),
            c.get("deliverable", ""),
            c.get("price_model", ""),
            c.get("monthly_300_path", ""),
            c.get("why_pay", ""),
            c.get("who_pays_now", ""),
            c.get("switching_reason", ""),
            now,
        ])
    if rows:
        append_rows("business_combos", rows)
    return len(rows)


def run_layer2(
    types: list[dict],
    ceo_constraints: dict,
    knowledge_context: str,
    run_id: str,
    batch_size: int = 5,
) -> list[dict]:
    all_combos: list[dict] = []
    combo_counter = 0

    for i in range(0, len(types), batch_size):
        batch = types[i:i + batch_size]
        batch_combos: list[dict] = []

        for btype in batch:
            logger.info(f"Layer 2: {btype['type_name']} ({btype.get('type_id', '?')})")
            try:
                combos = generate_combos_for_type(
                    business_type=btype,
                    ceo_constraints=ceo_constraints,
                    knowledge_context=knowledge_context,
                    run_id=run_id,
                )
                combos = _self_review_combos(combos, ceo_constraints)

                for c in combos:
                    combo_counter += 1
                    c["combo_id"] = f"BC-{combo_counter:04d}"

                batch_combos.extend(combos)
                logger.info(f"  → {len(combos)} combos")
            except Exception as e:
                logger.warning(f"Layer 2 failed for {btype.get('type_name')}: {e}")
                continue

            time.sleep(1.0)

        if batch_combos:
            _save_combos_to_sheet(batch_combos, run_id)
            all_combos.extend(batch_combos)

        try:
            from utils.cost_tracker import record_api_call
            record_api_call(
                run_id=run_id, phase="B_layer2",
                input_tokens=3000, output_tokens=5000,
                note=f"batch={i//batch_size + 1}",
            )
        except Exception:
            pass

        batch_num = (i // batch_size) + 1
        total_batches = (len(types) + batch_size - 1) // batch_size
        logger.info(
            f"Layer 2 batch {batch_num}/{total_batches}: "
            f"{len(batch_combos)} combos (累計: {len(all_combos)})"
        )

    logger.info(f"Layer 2 complete: {len(all_combos)} combos from {len(types)} types")
    return all_combos
