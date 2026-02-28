"""
Output validators for the pipeline.

V1 (ABC0): scoring-based validators (kept for backward compat)
V2: evidence-gate validators — PASS/FAIL only, no scores

Pure functions that validate JSON output from each pipeline step.
Returns ValidationResult with errors, warnings, and optionally corrected data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationResult:
    """Result of validating pipeline step output."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data: Any = None  # Optionally corrected/cleaned data


def _clamp(value: Any, low: float, high: float, label: str, warnings: list) -> float:
    """Clamp a numeric value to range, appending a warning if out of bounds."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        warnings.append(f"{label}: 数値に変換できません ({value})")
        return low
    if v < low:
        warnings.append(f"{label}: {v} → {low} にクランプ")
        return low
    if v > high:
        warnings.append(f"{label}: {v} → {high} にクランプ")
        return high
    return v


# ---------------------------------------------------------------------------
# Step A: Market Research validation
# ---------------------------------------------------------------------------
MARKET_RESEARCH_REQUIRED = [
    "market_name", "industry", "market_size_tam", "market_size_sam",
    "pest_political", "pest_economic", "pest_social", "pest_technological",
    "industry_structure", "key_players", "customer_pain_points", "entry_barriers",
]

def validate_market_research(
    data: list | dict,
    expected_segments: int = 3,
) -> ValidationResult:
    """Validate market research output from Step A."""
    errors: list[str] = []
    warnings: list[str] = []

    if isinstance(data, dict):
        data = [data]

    if not isinstance(data, list) or len(data) == 0:
        return ValidationResult(valid=False, errors=["空の結果または不正な型"])

    if len(data) != expected_segments:
        warnings.append(
            f"期待セグメント数 {expected_segments} に対し {len(data)} 件返却"
        )

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"セグメント[{i}]: dict型ではありません")
            continue

        for field_name in MARKET_RESEARCH_REQUIRED:
            val = item.get(field_name)
            if val is None or (isinstance(val, str) and not val.strip()):
                errors.append(f"セグメント[{i}]: 必須フィールド '{field_name}' が空")

        # List-type checks
        for list_field in ("key_players", "customer_pain_points"):
            val = item.get(list_field)
            if val is not None and not isinstance(val, list):
                warnings.append(
                    f"セグメント[{i}]: '{list_field}' がリスト型ではありません"
                )

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        data=data,
    )


# ---------------------------------------------------------------------------
# Step B: Market Selection validation (DEPRECATED — v2ではゲート制に移行)
# orchestrate_abc0.py の後方互換のために残す
# ---------------------------------------------------------------------------
SCORE_AXES = [
    "score_distortion_depth",
    "score_entry_barrier",
    "score_bpo_feasibility",
    "score_growth",
    "score_capability_fit",
]

DEFAULT_WEIGHTS = {
    "distortion": 3,
    "barrier": 2,
    "bpo": 2,
    "growth": 1.5,
    "capability": 1.5,
}

AXIS_TO_WEIGHT_KEY = {
    "score_distortion_depth": "distortion",
    "score_entry_barrier": "barrier",
    "score_bpo_feasibility": "bpo",
    "score_growth": "growth",
    "score_capability_fit": "capability",
}


def validate_market_selection(
    data: list | dict,
    weights: dict | None = None,
) -> ValidationResult:
    """Validate market selection scoring output from Step B. DEPRECATED in v2."""
    errors: list[str] = []
    warnings: list[str] = []
    w = weights or DEFAULT_WEIGHTS

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or len(data) == 0:
        return ValidationResult(valid=False, errors=["空の結果または不正な型"])

    cleaned = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"市場[{i}]: dict型ではありません")
            continue

        # market_research_id check
        if not item.get("market_research_id"):
            warnings.append(f"市場[{i}]: market_research_id が空")

        # Score range validation + clamping
        recalc_total = 0.0
        for axis in SCORE_AXES:
            raw = item.get(axis, 0)
            clamped = _clamp(raw, 1, 10, f"市場[{i}].{axis}", warnings)
            item[axis] = clamped
            weight_key = AXIS_TO_WEIGHT_KEY[axis]
            recalc_total += clamped * w.get(weight_key, 1)

        # Verify total_score consistency
        reported_total = 0.0
        try:
            reported_total = float(item.get("total_score", 0))
        except (TypeError, ValueError):
            pass

        if abs(reported_total - recalc_total) > 0.5:
            warnings.append(
                f"市場[{i}]: total_score 不整合 "
                f"(報告={reported_total:.1f}, 再計算={recalc_total:.1f}) → 再計算値を採用"
            )
            item["total_score"] = round(recalc_total, 1)

        cleaned.append(item)

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        data=cleaned,
    )


# ---------------------------------------------------------------------------
# Step C: Competitor Analysis validation
# ---------------------------------------------------------------------------
VALID_COMPETITOR_TYPES = {"direct", "indirect", "substitute"}


def validate_competitor_analysis(
    data: list | dict,
    expected_count: int = 5,
) -> ValidationResult:
    """Validate competitor analysis output from Step C."""
    errors: list[str] = []
    warnings: list[str] = []

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or len(data) == 0:
        return ValidationResult(valid=False, errors=["空の結果または不正な型"])

    if len(data) < expected_count:
        warnings.append(
            f"期待競合数 {expected_count} に対し {len(data)} 件返却"
        )

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"競合[{i}]: dict型ではありません")
            continue

        if not item.get("competitor_name"):
            errors.append(f"競合[{i}]: competitor_name が空")

        comp_type = item.get("competitor_type", "")
        if comp_type and comp_type not in VALID_COMPETITOR_TYPES:
            warnings.append(
                f"競合[{i}]: competitor_type '{comp_type}' は "
                f"{VALID_COMPETITOR_TYPES} のいずれでもありません"
            )

        gaps = item.get("gap_opportunities", [])
        if not isinstance(gaps, list) or len(gaps) == 0:
            warnings.append(f"競合[{i}]: gap_opportunities が空またはリスト型でない")

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        data=data,
    )


# ---------------------------------------------------------------------------
# Step 0: Idea Generation validation
# ---------------------------------------------------------------------------
def validate_idea_output(
    data: list | dict,
    expected_count: int = 3,
    check_ceo_fit: bool = False,
) -> ValidationResult:
    """Validate business idea output from Step 0."""
    errors: list[str] = []
    warnings: list[str] = []

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or len(data) == 0:
        return ValidationResult(valid=False, errors=["空の結果または不正な型"])

    if len(data) != expected_count:
        warnings.append(
            f"期待案数 {expected_count} に対し {len(data)} 件返却"
        )

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"事業案[{i}]: dict型ではありません")
            continue

        if not item.get("name"):
            errors.append(f"事業案[{i}]: name が空")

        desc = item.get("description", "")
        if len(desc) < 50:
            warnings.append(
                f"事業案[{i}]: description が短すぎます ({len(desc)}文字 < 50文字)"
            )

        if check_ceo_fit:
            score = item.get("ceo_fit_score")
            if score is not None:
                clamped = _clamp(score, 0, 100, f"事業案[{i}].ceo_fit_score", warnings)
                item["ceo_fit_score"] = clamped

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        data=data,
    )


# ---------------------------------------------------------------------------
# Step U: Unit Economics validation
# ---------------------------------------------------------------------------
def validate_unit_economics(data: list | dict) -> ValidationResult:
    """Validate unit economics output."""
    errors: list[str] = []
    warnings: list[str] = []

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or len(data) == 0:
        return ValidationResult(valid=False, errors=["空の結果または不正な型"])

    required_fields = ["ltv", "cac", "ltv_cac_ratio", "bep_months", "pricing_model"]

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"UE[{i}]: dict型ではありません")
            continue

        for f in required_fields:
            if f not in item or item[f] is None:
                warnings.append(f"UE[{i}]: '{f}' が未設定")

        # LTV/CAC ratio sanity check
        try:
            ratio = float(item.get("ltv_cac_ratio", 0))
            if ratio < 1:
                warnings.append(f"UE[{i}]: LTV/CAC比率 {ratio} < 1（赤字モデル）")
            elif ratio > 20:
                warnings.append(f"UE[{i}]: LTV/CAC比率 {ratio} > 20（過大推定の可能性）")
        except (TypeError, ValueError):
            pass

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        data=data,
    )


# ---------------------------------------------------------------------------
# Step E: Checklist Evaluation validation
# ---------------------------------------------------------------------------
def validate_checklist_evaluation(data: list | dict) -> ValidationResult:
    """Validate checklist evaluation output."""
    errors: list[str] = []
    warnings: list[str] = []

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or len(data) == 0:
        return ValidationResult(valid=False, errors=["空の結果または不正な型"])

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"チェック[{i}]: dict型ではありません")
            continue

        score = item.get("score")
        if score is not None:
            clamped = _clamp(score, 0, 100, f"チェック[{i}].score", warnings)
            item["score"] = clamped

        answers = item.get("answers", [])
        if not isinstance(answers, list) or len(answers) == 0:
            warnings.append(f"チェック[{i}]: answers が空")

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        data=data,
    )


# ---------------------------------------------------------------------------
# Layer 1: Business Model Type validation
# ---------------------------------------------------------------------------
TYPE_REQUIRED_FIELDS = [
    "type_name", "description", "revenue_model", "example",
]


def validate_business_model_types(
    data: list | dict,
    min_count: int = 10,
) -> ValidationResult:
    """Validate Layer 1 business model type output."""
    errors: list[str] = []
    warnings: list[str] = []

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or len(data) == 0:
        return ValidationResult(valid=False, errors=["空の結果または不正な型"])

    if len(data) < min_count:
        warnings.append(f"最低{min_count}型に対し{len(data)}型のみ")

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"型[{i}]: dict型ではありません")
            continue

        for fname in TYPE_REQUIRED_FIELDS:
            val = item.get(fname)
            if val is None or (isinstance(val, str) and not val.strip()):
                errors.append(f"型[{i}]: 必須フィールド '{fname}' が空")

        desc = item.get("description", "")
        if isinstance(desc, str) and len(desc) < 10:
            warnings.append(f"型[{i}]: descriptionが短すぎます ({len(desc)}文字)")

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        data=data,
    )


# ---------------------------------------------------------------------------
# Layer 2: Business Combo validation
# ---------------------------------------------------------------------------
COMBO_REQUIRED_FIELDS = [
    "business_name", "target", "deliverable", "price_model", "monthly_300_path",
]


def validate_business_combos(
    data: list | dict,
    min_count: int = 3,
) -> ValidationResult:
    """Validate Layer 2 business combo output."""
    errors: list[str] = []
    warnings: list[str] = []

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or len(data) == 0:
        return ValidationResult(valid=False, errors=["空の結果または不正な型"])

    if len(data) < min_count:
        warnings.append(f"最低{min_count}件に対し{len(data)}件のみ")

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"コンボ[{i}]: dict型ではありません")
            continue

        for fname in COMBO_REQUIRED_FIELDS:
            val = item.get(fname)
            if val is None or (isinstance(val, str) and not val.strip()):
                errors.append(f"コンボ[{i}]: 必須フィールド '{fname}' が空")

        name = item.get("business_name", "")
        if isinstance(name, str) and len(name) < 10:
            warnings.append(f"コンボ[{i}]: business_nameが短すぎます ({len(name)}文字)")

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        data=data,
    )


# ===========================================================================
# V2 Gate Validators — 証拠ベースPASS/FAIL判定（スコアリング禁止）
# ===========================================================================

def validate_a1_quick(data: list | dict) -> ValidationResult:
    """Validate A1-quick gate results.

    Each micro-market must have:
    - payment_evidence_urls (支払い証拠URL 1件以上)
    - At least 1 category (demand/seriousness/tailwind) with concrete value + URL
    """
    errors: list[str] = []
    warnings: list[str] = []

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or len(data) == 0:
        return ValidationResult(valid=False, errors=["空の結果または不正な型"])

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"マイクロ市場[{i}]: dict型ではありません")
            continue

        # Payment evidence URL required
        pay_urls = item.get("payment_evidence_urls", [])
        if not pay_urls or (isinstance(pay_urls, list) and len(pay_urls) == 0):
            item["status"] = "FAIL"
            item["fail_reason"] = "支払い証拠URLなし"
            continue

        # At least 1 category with concrete value + URL
        categories_met = 0

        # Format A: separate keys (demand_evidence, seriousness_evidence, tailwind_evidence)
        for cat_key in ("demand_evidence", "seriousness_evidence", "tailwind_evidence"):
            ev = item.get(cat_key, {})
            if isinstance(ev, dict) and ev.get("value") and ev.get("url"):
                categories_met += 1

        # Format B: single category_evidence object (current prompt format)
        cat_ev = item.get("category_evidence", {})
        if isinstance(cat_ev, dict) and cat_ev.get("value") and cat_ev.get("url"):
            categories_met += 1

        if categories_met == 0:
            item["status"] = "FAIL"
            item["fail_reason"] = "需要/本気度/追い風のいずれにも具体値+URLなし"
        else:
            item["status"] = "PASS"

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        data=data,
    )


# A1-deep gate: 8 conditions (a-h), all must be met
A1_DEEP_CONDITIONS = {
    "a_payer": "支払者特定（部署/役職）",
    "b_price_evidence": "価格URL3件 or 見積URL5件 or 導入事例3件+見積2件",
    "c_tailwind_urls": "追い風根拠URL 2件",
    "d_seriousness_urls": "VC調達URL2件 or 本気度証拠URL2件",
    "e_search_metrics": "検索数/CPC/トレンドのうち2つ",
    "f_competitor_urls": "競合URL 10社以上（実名+URL）",
    "g_gaps": "穴3つ（各穴に根拠URL 1件）",
    "h_blackout_hypothesis": "10社黒字化仮説",
}


def validate_a1_deep(data: dict) -> ValidationResult:
    """Validate A1-deep gate results. All 8 conditions (a-h) must be met."""
    errors: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []

    if not isinstance(data, dict):
        return ValidationResult(valid=False, errors=["dict型ではありません"])

    # a: payer identification
    payer = data.get("a_payer", {})
    if not (isinstance(payer, dict) and payer.get("department") and payer.get("role")):
        missing.append("a: " + A1_DEEP_CONDITIONS["a_payer"])

    # b: price evidence
    b = data.get("b_price_evidence", {})
    price_urls = b.get("price_urls", []) if isinstance(b, dict) else []
    quote_urls = b.get("quote_urls", []) if isinstance(b, dict) else []
    case_urls = b.get("case_urls", []) if isinstance(b, dict) else []
    b_ok = (
        len(price_urls) >= 3
        or len(quote_urls) >= 5
        or (len(case_urls) >= 3 and len(quote_urls) >= 2)
    )
    if not b_ok:
        missing.append("b: " + A1_DEEP_CONDITIONS["b_price_evidence"])

    # c: tailwind URLs (2+)
    c_urls = data.get("c_tailwind_urls", [])
    if not isinstance(c_urls, list) or len(c_urls) < 2:
        missing.append("c: " + A1_DEEP_CONDITIONS["c_tailwind_urls"])

    # d: seriousness/VC evidence
    d = data.get("d_seriousness_urls", {})
    vc_urls = d.get("vc_urls", []) if isinstance(d, dict) else []
    serious_urls = d.get("seriousness_urls", []) if isinstance(d, dict) else []
    if not (len(vc_urls) >= 2 or len(serious_urls) >= 2):
        missing.append("d: " + A1_DEEP_CONDITIONS["d_seriousness_urls"])

    # e: search metrics (2 of 3)
    e = data.get("e_search_metrics", {})
    e_count = sum(1 for k in ("search_volume", "cpc", "trend") if e.get(k)) if isinstance(e, dict) else 0
    if e_count < 2:
        missing.append("e: " + A1_DEEP_CONDITIONS["e_search_metrics"])

    # f: competitor URLs (10+)
    f_comps = data.get("f_competitor_urls", [])
    if not isinstance(f_comps, list) or len(f_comps) < 10:
        missing.append("f: " + A1_DEEP_CONDITIONS["f_competitor_urls"])

    # g: gaps (3, each with evidence URL)
    g_gaps = data.get("g_gaps", [])
    if not isinstance(g_gaps, list) or len(g_gaps) < 3:
        missing.append("g: " + A1_DEEP_CONDITIONS["g_gaps"])
    else:
        for gi, gap in enumerate(g_gaps[:3]):
            if isinstance(gap, dict) and not gap.get("evidence_url"):
                missing.append(f"g: 穴{gi+1}に根拠URLなし")

    # h: blackout hypothesis
    h = data.get("h_blackout_hypothesis", "")
    if not h or (isinstance(h, str) and len(h.strip()) < 20):
        missing.append("h: " + A1_DEEP_CONDITIONS["h_blackout_hypothesis"])

    status = "FAIL" if missing else "PASS"
    data["gate_status"] = status
    data["missing_items"] = missing

    return ValidationResult(
        valid=len(errors) == 0 and len(missing) == 0,
        errors=errors,
        warnings=warnings,
        data=data,
    )


def validate_competitor_20(data: list | dict) -> ValidationResult:
    """Validate 20-company competitor template output.

    Accepts two formats:
      - Format A (full response): {"competitors": [...], "gap_top3": [...]}
      - Format B (list only): [{"company_name": ...}, ...]
    """
    errors: list[str] = []
    warnings: list[str] = []
    gap_top3: list = []

    # Format A: full response object with "competitors" key
    if isinstance(data, dict) and "competitors" in data:
        gap_top3 = data.get("gap_top3", [])
        competitors = data.get("competitors", [])
        if not isinstance(competitors, list):
            return ValidationResult(valid=False, errors=["competitors が配列ではありません"])
        data = competitors  # validate the competitors list below

    # Format B: plain list of competitors
    elif isinstance(data, list):
        pass  # already a list

    # Fallback: single competitor dict (no "competitors" key)
    elif isinstance(data, dict):
        data = [data]

    if not isinstance(data, list) or len(data) == 0:
        return ValidationResult(valid=False, errors=["空の結果または不正な型"])

    if len(data) < 20:
        warnings.append(f"競合20社に対し {len(data)} 件のみ返却")

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"競合[{i}]: dict型ではありません")
            continue

        if not item.get("company_name"):
            errors.append(f"競合[{i}]: company_name が空")

        if not item.get("url"):
            warnings.append(f"競合[{i}]: URLが空（{item.get('company_name', '不明')}）")

    # Return the full structure (competitors + gap_top3) for downstream use
    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        data={"competitors": data, "gap_top3": gap_top3},
    )


# Offer 3: mandatory 7 fields
OFFER_REQUIRED_FIELDS = [
    "payer", "offer_name", "deliverable",
    "time_to_value", "price", "replaces", "upsell",
]


def validate_offer_3(data: list | dict) -> ValidationResult:
    """Validate 3 instant-decision offers. All 7 fields mandatory."""
    errors: list[str] = []
    warnings: list[str] = []

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or len(data) == 0:
        return ValidationResult(valid=False, errors=["空の結果または不正な型"])

    if len(data) != 3:
        warnings.append(f"期待3案に対し {len(data)} 案返却")

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"オファー[{i}]: dict型ではありません")
            continue

        for fname in OFFER_REQUIRED_FIELDS:
            val = item.get(fname)
            if val is None or (isinstance(val, str) and not val.strip()):
                errors.append(f"オファー[{i}]: 必須フィールド '{fname}' が空")

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        data=data,
    )
