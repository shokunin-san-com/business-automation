"""
CEO profile loader — provides CEO career context for prompt injection.

Reads use_ceo_profile flag and ceo_profile_json from settings sheet.
Returns formatted context string or empty string based on toggle.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_logger
from utils.sheets_client import get_all_rows

logger = get_logger("ceo_profile")


def _load_settings() -> dict:
    rows = get_all_rows("settings")
    return {r["key"]: r["value"] for r in rows}


def is_ceo_profile_enabled() -> bool:
    """Check if CEO profile scoring is enabled."""
    settings = _load_settings()
    return settings.get("use_ceo_profile", "false").lower() == "true"


def get_ceo_profile_context() -> str:
    """Get CEO profile formatted for prompt injection.

    Returns empty string if use_ceo_profile is false.
    Supports both JSON format (legacy) and free-text format.
    """
    settings = _load_settings()

    if settings.get("use_ceo_profile", "false").lower() != "true":
        return ""

    raw = settings.get("ceo_profile_json", "").strip()
    if not raw:
        return ""

    # Try JSON format first (legacy support)
    try:
        profile = json.loads(raw)
        parts = [
            f"CEO: {profile.get('name', 'N/A')}",
            "",
            "## 強み・経験",
        ]
        for s in profile.get("strengths", []):
            parts.append(f"- {s}")

        parts.append("")
        parts.append(f"## 得意業界: {', '.join(profile.get('industries', []))}")
        parts.append(f"## モチベーション: {', '.join(profile.get('motivators', []))}")
        parts.append(f"## 保有資格・許認可: {', '.join(profile.get('licenses', []))}")

        return "\n".join(parts)
    except (json.JSONDecodeError, AttributeError):
        pass

    # Free-text format: return as-is
    logger.info("Using free-text CEO profile")
    return raw
