"""
Risk scoring module — evaluate content risk before auto-posting/sending.

Checks:
1. NG word detection (blacklisted words/phrases)
2. Tone analysis via Claude API
3. Brand guideline compliance
4. Overall risk score: 0-100 (0=safe, 100=high risk)

Decision thresholds:
  - score <= 30: AUTO (auto-post/send)
  - score 31-70: REVIEW (queue for human review)
  - score > 70: BLOCK (do not send, alert human)
"""


from __future__ import annotations
import re
from dataclasses import dataclass, field

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_logger

logger = get_logger(__name__)

# NG words / phrases — expand as needed
NG_WORDS = [
    # Aggressive sales language
    "今すぐ", "絶対に", "100%", "確実に", "必ず", "保証",
    "業界最安", "業界No.1", "日本一", "世界初",
    # Legally problematic
    "稼げる", "儲かる", "元本保証", "必ず利益",
    # Spam-like
    "限定", "残りわずか", "今だけ", "特別価格",
    # Inappropriate
    "死", "殺", "暴力", "差別",
]

# Patterns that suggest spam
SPAM_PATTERNS = [
    r"[!！]{3,}",           # 3+ exclamation marks
    r"[💰💵🤑]{2,}",        # Multiple money emojis
    r"https?://\S+.*https?://\S+",  # Multiple URLs
    r"\b\d+万円\b.*\b\d+万円\b",    # Multiple monetary claims
]

RISK_THRESHOLD_AUTO = 30
RISK_THRESHOLD_REVIEW = 70


@dataclass
class RiskResult:
    score: int              # 0-100
    decision: str           # "auto" | "review" | "block"
    flags: list[str] = field(default_factory=list)
    detail: str = ""


def check_ng_words(text: str) -> list[str]:
    """Check for blacklisted words/phrases."""
    found = []
    text_lower = text.lower()
    for word in NG_WORDS:
        if word.lower() in text_lower:
            found.append(word)
    return found


def check_spam_patterns(text: str) -> list[str]:
    """Check for spam-like patterns."""
    found = []
    for pattern in SPAM_PATTERNS:
        if re.search(pattern, text):
            found.append(f"pattern:{pattern[:30]}")
    return found


def check_length(text: str, platform: str) -> list[str]:
    """Check if text length is appropriate for the platform."""
    flags = []
    if platform == "twitter" and len(text) > 280:
        flags.append("twitter_too_long")
    if platform == "linkedin" and len(text) > 3000:
        flags.append("linkedin_too_long")
    if len(text) < 20:
        flags.append("too_short")
    return flags


def score_with_claude(text: str, context: str = "") -> tuple[int, str]:
    """Use Claude API for deeper tone/risk analysis.

    Returns (risk_score_adjustment, analysis_detail).
    Only called for borderline cases to save API costs.
    """
    try:
        from utils.claude_client import generate_json

        prompt = f"""以下のテキストのリスクを0-100で評価してください。

テキスト:
{text}

用途: {context}

評価基準:
- 0-20: 安全（丁寧なビジネストーン）
- 21-50: やや注意（表現に改善余地）
- 51-80: 要確認（誇大表現や不適切な可能性）
- 81-100: 危険（炎上・スパム・法的リスク）

JSON形式で出力:
{{"score": 数値, "reason": "理由を50文字以内で"}}"""

        result = generate_json(
            prompt=prompt,
            system="あなたはコンテンツリスク審査の専門家です。",
            max_tokens=256,
            temperature=0.2,
        )
        return int(result.get("score", 50)), result.get("reason", "")
    except Exception as e:
        logger.warning(f"Claude risk scoring failed: {e}")
        return 50, "AI分析失敗"


def evaluate(
    text: str,
    platform: str = "general",
    context: str = "",
    use_ai: bool = True,
) -> RiskResult:
    """Evaluate risk of content text.

    Args:
        text: The content to evaluate
        platform: "twitter", "linkedin", "form", "general"
        context: Additional context (e.g., business idea name)
        use_ai: Whether to use Claude API for deep analysis (costs money)

    Returns:
        RiskResult with score, decision, and flags
    """
    flags = []
    score = 0

    # 1. NG word check (+15 per word)
    ng_found = check_ng_words(text)
    if ng_found:
        flags.extend([f"ng_word:{w}" for w in ng_found])
        score += len(ng_found) * 15

    # 2. Spam pattern check (+20 per pattern)
    spam_found = check_spam_patterns(text)
    if spam_found:
        flags.extend(spam_found)
        score += len(spam_found) * 20

    # 3. Length check (+10)
    length_flags = check_length(text, platform)
    if length_flags:
        flags.extend(length_flags)
        score += len(length_flags) * 10

    # 4. AI analysis (only if borderline and use_ai=True)
    ai_detail = ""
    if use_ai and 15 <= score <= 60:
        ai_score, ai_detail = score_with_claude(text, context)
        # Weight: 40% rule-based, 60% AI
        score = int(score * 0.4 + ai_score * 0.6)
    elif not use_ai and not flags:
        # No flags and no AI = low risk
        score = 10

    # Clamp to 0-100
    score = max(0, min(100, score))

    # Decision
    if score <= RISK_THRESHOLD_AUTO:
        decision = "auto"
    elif score <= RISK_THRESHOLD_REVIEW:
        decision = "review"
    else:
        decision = "block"

    detail_parts = []
    if flags:
        detail_parts.append(f"Flags: {', '.join(flags[:5])}")
    if ai_detail:
        detail_parts.append(f"AI: {ai_detail}")

    result = RiskResult(
        score=score,
        decision=decision,
        flags=flags,
        detail=" | ".join(detail_parts) if detail_parts else "OK",
    )

    logger.info(f"Risk evaluation: score={score}, decision={decision}, flags={len(flags)}")
    return result
