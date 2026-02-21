"""
Output validators for the ABC0 autonomous pipeline.

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
# Step B: Market Selection validation
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
    """Validate market selection scoring output from Step B."""
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
