"""
Consistency Checker — validates pipeline output integrity via snapshot diff.

Takes snapshots of Google Sheets before and after orchestrate_abc0 execution,
computes a consistency score (0-100) based on the DELTA, and alerts if score < 60.

Scoring breakdown (100 points total):
  - market_research rows added:     40 pts (vs expected = markets × segments)
  - market_selection selected:      30 pts (vs expected = selection_top_n)
  - business_ideas rows added:      20 pts (vs expected = ideas_per_run)
  - No pipeline errors:             10 pts (no ERROR in recent logs)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from agent.tools.sheets_reader import read_sheet
from agent.tools.logs_reader import read_logs
from agent.config import get_logger

logger = get_logger(__name__)

JST = timezone(timedelta(hours=9))

DEFAULT_SNAPSHOT_PATH = "/tmp/mp_snapshot_before.json"


@dataclass
class ConsistencyResult:
    """Result of a consistency check."""
    score: int  # 0-100
    breakdown: dict
    before: dict
    after: dict
    diff: dict
    errors: list[str]

    @property
    def is_healthy(self) -> bool:
        return self.score >= 60

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "is_healthy": self.is_healthy,
            "breakdown": self.breakdown,
            "before": self.before,
            "after": self.after,
            "diff": self.diff,
            "errors": self.errors,
        }

    def summary(self) -> str:
        """Human-readable summary."""
        icon = "✅" if self.is_healthy else "❌"
        lines = [
            f"{icon} 整合性スコア: {self.score}/100",
            "",
            "内訳:",
        ]
        for key, val in self.breakdown.items():
            lines.append(f"  {key}: {val}")
        lines.append("")
        lines.append("差分:")
        for key, val in self.diff.items():
            before_val = self.before.get(key, 0)
            after_val = self.after.get(key, 0)
            lines.append(f"  {key}: {before_val} → {after_val} (+{val})")
        if self.errors:
            lines.append("\nエラー:")
            for e in self.errors:
                lines.append(f"  ❌ {e}")
        return "\n".join(lines)


def _count_rows(sheet_name: str) -> int:
    """Count total rows in a sheet."""
    return len(read_sheet(sheet_name, row_limit=1000))


def _count_status(sheet_name: str, status_value: str) -> int:
    """Count rows with a specific status value."""
    rows = read_sheet(sheet_name, row_limit=1000)
    return sum(1 for r in rows if r.get("status", "").lower() == status_value.lower())


def _read_settings() -> dict:
    """Read settings sheet as key-value dict."""
    rows = read_sheet("settings", row_limit=100)
    return {row["key"]: row["value"] for row in rows if row.get("key")}


def _no_errors_in_logs(minutes: int = 60) -> bool:
    """Check if there are any ERROR logs in the last N minutes."""
    entries = read_logs(severity="ERROR", minutes=minutes, limit=1)
    return len(entries) == 0


# ═══════════════════════════════════════════════════════════
# Snapshot save / load
# ═══════════════════════════════════════════════════════════


def save_snapshot(path: str = DEFAULT_SNAPSHOT_PATH) -> str:
    """
    Save current Sheets state to a JSON file (call BEFORE pipeline execution).

    Captures:
      - market_research row count
      - market_selection row count
      - business_ideas row count
      - selected_count (market_selection rows with status='selected')
      - ideas_approved (business_ideas rows with status='approved')

    Args:
        path: File path to save the snapshot JSON.

    Returns:
        The path where the snapshot was saved.
    """
    snapshot = {
        "taken_at": datetime.now(JST).isoformat(),
        "market_research": _count_rows("market_research"),
        "market_selection": _count_rows("market_selection"),
        "business_ideas": _count_rows("business_ideas"),
        "selected_count": _count_status("market_selection", "selected"),
        "ideas_approved": _count_status("business_ideas", "approved"),
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    logger.info(
        "Snapshot saved: MR=%d, MS=%d, BI=%d → %s",
        snapshot["market_research"],
        snapshot["market_selection"],
        snapshot["business_ideas"],
        path,
    )
    return path


def _load_snapshot(path: str) -> dict:
    """Load a previously saved snapshot from JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════
# Diff-based consistency check
# ═══════════════════════════════════════════════════════════


def check_with_snapshot(before_path: str = DEFAULT_SNAPSHOT_PATH) -> ConsistencyResult:
    """
    Compare saved snapshot (before) with current state (after) and compute score.

    Call this AFTER pipeline execution. Requires save_snapshot() to have been
    called before execution.

    Args:
        before_path: Path to the before-snapshot JSON file.

    Returns:
        ConsistencyResult with score, breakdown, diff, and errors.

    Raises:
        ValueError: If the snapshot file doesn't exist.
    """
    if not os.path.exists(before_path):
        raise ValueError(
            f"スナップショットが見つかりません: {before_path}\n"
            "実行前に save_snapshot() を呼んでください。"
        )

    before = _load_snapshot(before_path)

    # Take current state as "after"
    after = {
        "market_research": _count_rows("market_research"),
        "market_selection": _count_rows("market_selection"),
        "business_ideas": _count_rows("business_ideas"),
        "selected_count": _count_status("market_selection", "selected"),
        "ideas_approved": _count_status("business_ideas", "approved"),
    }

    # Calculate diff (only numeric keys)
    diff_keys = ["market_research", "market_selection", "business_ideas",
                 "selected_count", "ideas_approved"]
    diff = {k: after[k] - before.get(k, 0) for k in diff_keys}

    # Score based on diff
    score, breakdown, errors = _calc_score(diff)

    result = ConsistencyResult(
        score=score,
        breakdown=breakdown,
        before=before,
        after=after,
        diff=diff,
        errors=errors,
    )

    logger.info("Consistency score: %d/100 (healthy=%s)", score, result.is_healthy)
    return result


def _calc_score(diff: dict) -> tuple[int, dict, list[str]]:
    """
    Calculate consistency score from diff values.

    Uses settings sheet to determine expected counts:
      - expected_research = len(exploration_markets) × exploration_segments_per_market
      - expected_selected = selection_top_n
      - expected_ideas    = ideas_per_run

    Scoring:
      - 市場調査:   max 40 pts (achievement rate × 40)
      - 市場選定:   max 30 pts (achievement rate × 30)
      - 事業案生成: max 20 pts (achievement rate × 20)
      - エラーなし: max 10 pts (no ERROR logs in last 60 min)

    Returns:
        Tuple of (total_score, breakdown_dict, errors_list).
    """
    settings = _read_settings()
    errors = []

    # Expected values from settings
    exploration_markets = settings.get("exploration_markets", "")
    markets_count = len([m.strip() for m in exploration_markets.split(",") if m.strip()]) if exploration_markets else 1
    seg_per_mkt = _safe_int(settings.get("exploration_segments_per_market", "3"))
    top_n = _safe_int(settings.get("selection_top_n", "3"))
    ideas_per = _safe_int(settings.get("ideas_per_run", "3"))

    expected_research = markets_count * seg_per_mkt
    expected_selected = top_n
    expected_ideas = ideas_per

    # Achievement rates (clamped to 1.0)
    r1 = min(diff.get("market_research", 0) / max(expected_research, 1), 1.0)
    r2 = min(diff.get("selected_count", 0) / max(expected_selected, 1), 1.0)
    r3 = min(diff.get("business_ideas", 0) / max(expected_ideas, 1), 1.0)

    s1 = round(r1 * 40)  # 市場調査   max 40
    s2 = round(r2 * 30)  # 市場選定   max 30
    s3 = round(r3 * 20)  # 事業案生成 max 20
    s4 = 10 if _no_errors_in_logs(minutes=60) else 0  # エラーなし max 10

    total = s1 + s2 + s3 + s4

    # Track errors
    if diff.get("market_research", 0) == 0:
        errors.append("市場調査の行が追加されていません")
    if diff.get("selected_count", 0) == 0:
        errors.append("市場選定（selected）が追加されていません")
    if diff.get("business_ideas", 0) == 0:
        errors.append("事業案が生成されていません")
    if s4 == 0:
        errors.append("直近60分にERRORログが検出されています")

    breakdown = {
        "市場調査": f"{s1}/40  (期待{expected_research}件 → 実績+{diff.get('market_research', 0)}件)",
        "市場選定": f"{s2}/30  (期待{expected_selected}件 → 実績+{diff.get('selected_count', 0)}件)",
        "事業案生成": f"{s3}/20  (期待{expected_ideas}件 → 実績+{diff.get('business_ideas', 0)}件)",
        "エラーなし": f"{s4}/10",
    }

    return total, breakdown, errors


def _safe_int(value: str | int, default: int = 3) -> int:
    """Safely convert a value to int."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default
