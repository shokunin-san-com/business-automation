"""
strength_matcher.py — Programmatic CEO profile × market fit matching.

No AI calls — pure keyword matching.
Returns: STRONG_FIT / MODERATE_FIT / WEAK_FIT
"""
from __future__ import annotations

LICENSE_KEYWORDS = [
    "有料職業紹介", "特定技能", "登録支援", "M&A", "電気工事士",
    "人材紹介事業", "紹介事業", "登録支援機関",
]

INDUSTRY_KEYWORDS = [
    "建設", "施工管理", "設備設計", "インフラ", "エネルギー",
    "蓄電池", "人材紹介", "建機", "建築", "土木", "工事",
]

SKILL_KEYWORDS = [
    "DD", "バリュエーション", "PMI", "海外", "ベトナム",
    "IR", "経営企画", "ソーシング", "売却", "創業",
]


def match_strength(combo: dict, ceo_profile: str) -> str:
    """Match CEO profile against a business combo.

    Args:
        combo: dict with business_name, target, deliverable, etc.
        ceo_profile: freeform text of CEO's experience/licenses.

    Returns:
        "STRONG_FIT" | "MODERATE_FIT" | "WEAK_FIT"
    """
    if not ceo_profile:
        return "WEAK_FIT"

    combo_text = " ".join(
        str(v) for v in combo.values() if isinstance(v, str)
    ).lower()
    profile_lower = ceo_profile.lower()

    license_hits = sum(
        1 for kw in LICENSE_KEYWORDS
        if kw.lower() in combo_text and kw.lower() in profile_lower
    )

    industry_hits = sum(
        1 for kw in INDUSTRY_KEYWORDS
        if kw.lower() in combo_text and kw.lower() in profile_lower
    )

    skill_hits = sum(
        1 for kw in SKILL_KEYWORDS
        if kw.lower() in combo_text and kw.lower() in profile_lower
    )

    if license_hits >= 1:
        return "STRONG_FIT"
    if industry_hits >= 3 or (industry_hits >= 1 and skill_hits >= 1):
        return "STRONG_FIT"
    if industry_hits >= 1 or skill_hits >= 1:
        return "MODERATE_FIT"
    return "WEAK_FIT"
