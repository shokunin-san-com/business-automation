"""
Consistency Checker — validates V2 pipeline output integrity via snapshot diff.

Takes snapshots of Google Sheets before and after orchestrate_v2 execution,
computes a consistency score (0-100) based on the DELTA, and alerts if score < 60.

V2 Scoring breakdown (100 points total):
  - micro_market_list rows added:   30 pts (A0 micro-market generation)
  - gate_decision_log entries:      25 pts (A1q/A1d gate decisions)
  - competitor_20_log entries:      20 pts (C: competitor analysis)
  - offer_3_log entries:            15 pts (0: offer generation)
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
    Save current V2 Sheets state to a JSON file (call BEFORE pipeline execution).

    Captures:
      - micro_market_list row count
      - gate_decision_log row count (+ PASS count)
      - competitor_20_log row count
      - offer_3_log row count
      - lp_ready_log row count (+ READY count)

    Args:
        path: File path to save the snapshot JSON.

    Returns:
        The path where the snapshot was saved.
    """
    snapshot = {
        "taken_at": datetime.now(JST).isoformat(),
        "micro_market_list": _count_rows("micro_market_list"),
        "gate_decision_log": _count_rows("gate_decision_log"),
        "gate_pass_count": _count_status("gate_decision_log", "PASS"),
        "competitor_20_log": _count_rows("competitor_20_log"),
        "offer_3_log": _count_rows("offer_3_log"),
        "lp_ready_log": _count_rows("lp_ready_log"),
        "lp_ready_count": _count_status("lp_ready_log", "READY"),
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    logger.info(
        "Snapshot saved: MML=%d, GDL=%d(PASS=%d), C20=%d, O3=%d, LR=%d(READY=%d) → %s",
        snapshot["micro_market_list"],
        snapshot["gate_decision_log"],
        snapshot["gate_pass_count"],
        snapshot["competitor_20_log"],
        snapshot["offer_3_log"],
        snapshot["lp_ready_log"],
        snapshot["lp_ready_count"],
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
        "micro_market_list": _count_rows("micro_market_list"),
        "gate_decision_log": _count_rows("gate_decision_log"),
        "gate_pass_count": _count_status("gate_decision_log", "PASS"),
        "competitor_20_log": _count_rows("competitor_20_log"),
        "offer_3_log": _count_rows("offer_3_log"),
        "lp_ready_log": _count_rows("lp_ready_log"),
        "lp_ready_count": _count_status("lp_ready_log", "READY"),
    }

    # Calculate diff (only numeric keys)
    diff_keys = [
        "micro_market_list", "gate_decision_log", "gate_pass_count",
        "competitor_20_log", "offer_3_log", "lp_ready_log", "lp_ready_count",
    ]
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
    Calculate V2 consistency score from diff values.

    V2 Scoring (evidence-based pipeline):
      - マイクロ市場生成 (A0):    max 30 pts
      - ゲート判定 (A1q/A1d):     max 25 pts
      - 競合20社分析 (C):         max 20 pts
      - オファー生成 (0):         max 15 pts
      - エラーなし:               max 10 pts

    Returns:
        Tuple of (total_score, breakdown_dict, errors_list).
    """
    settings = _read_settings()
    errors = []

    # Expected values from settings
    exploration_markets = settings.get("exploration_markets", "")
    markets_count = len([m.strip() for m in exploration_markets.split(",") if m.strip()]) if exploration_markets else 1
    seg_per_mkt = _safe_int(settings.get("exploration_segments_per_market", "3"))

    expected_micro_markets = markets_count * seg_per_mkt
    # Gate decisions should exist for at least top-N markets
    expected_gate_decisions = _safe_int(settings.get("a1_deep_top_n", "5"))
    # Competitor analysis for PASS markets (at least 1)
    expected_competitor = max(diff.get("gate_pass_count", 0), 1)
    # Offers for markets with competitor analysis
    expected_offers = max(diff.get("gate_pass_count", 0), 1)

    # Achievement rates (clamped to 1.0)
    r1 = min(diff.get("micro_market_list", 0) / max(expected_micro_markets, 1), 1.0)
    r2 = min(diff.get("gate_decision_log", 0) / max(expected_gate_decisions, 1), 1.0)
    r3 = min(diff.get("competitor_20_log", 0) / max(expected_competitor, 1), 1.0)
    r4 = min(diff.get("offer_3_log", 0) / max(expected_offers, 1), 1.0)

    s1 = round(r1 * 30)  # マイクロ市場生成 max 30
    s2 = round(r2 * 25)  # ゲート判定       max 25
    s3 = round(r3 * 20)  # 競合20社分析     max 20
    s4 = round(r4 * 15)  # オファー生成     max 15
    s5 = 10 if _no_errors_in_logs(minutes=60) else 0  # エラーなし max 10

    total = s1 + s2 + s3 + s4 + s5

    # Track errors
    if diff.get("micro_market_list", 0) == 0:
        errors.append("マイクロ市場が生成されていません (A0)")
    if diff.get("gate_decision_log", 0) == 0:
        errors.append("ゲート判定が実行されていません (A1)")
    if diff.get("competitor_20_log", 0) == 0 and diff.get("gate_pass_count", 0) > 0:
        errors.append("PASSした市場の競合分析が実行されていません (C)")
    if diff.get("offer_3_log", 0) == 0 and diff.get("gate_pass_count", 0) > 0:
        errors.append("PASSした市場のオファーが生成されていません (0)")
    if s5 == 0:
        errors.append("直近60分にERRORログが検出されています")

    breakdown = {
        "マイクロ市場(A0)": f"{s1}/30  (期待{expected_micro_markets}件 → 実績+{diff.get('micro_market_list', 0)}件)",
        "ゲート判定(A1)": f"{s2}/25  (期待{expected_gate_decisions}件 → 実績+{diff.get('gate_decision_log', 0)}件)",
        "競合分析(C)": f"{s3}/20  (期待{expected_competitor}件 → 実績+{diff.get('competitor_20_log', 0)}件)",
        "オファー(0)": f"{s4}/15  (期待{expected_offers}件 → 実績+{diff.get('offer_3_log', 0)}件)",
        "エラーなし": f"{s5}/10",
    }

    return total, breakdown, errors


def _safe_int(value: str | int, default: int = 3) -> int:
    """Safely convert a value to int."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default
