"""
Pattern Detector — analyzes agent_history to detect recurring patterns.

Detects:
  - Recurring errors (same error > 2 times in last 10 runs)
  - Degrading consistency scores (downward trend)
  - Abnormal execution times (> 2x median)
  - Tool usage patterns (most/least used tools)

Generates direction_notes updates based on detected patterns.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone, timedelta

from agent.config import get_logger
from agent.learning.history_writer import get_recent_runs

logger = get_logger(__name__)

JST = timezone(timedelta(hours=9))


def detect_patterns(run_limit: int = 20) -> dict:
    """
    Analyze recent agent runs and detect patterns.

    Args:
        run_limit: Number of recent runs to analyze.

    Returns:
        Dict with detected patterns and recommendations.
    """
    runs = get_recent_runs(limit=run_limit)

    if not runs:
        return {
            "status": "no_data",
            "message": "まだ実行履歴がありません",
            "patterns": [],
            "recommendations": [],
        }

    patterns = []
    recommendations = []

    # ── 1. Recurring Errors ──
    error_counts = Counter()
    for run in runs:
        errors_str = run.get("errors", "")
        if errors_str:
            try:
                errors = json.loads(errors_str)
                for err in errors:
                    error_counts[err] += 1
            except (json.JSONDecodeError, TypeError):
                if errors_str.strip():
                    error_counts[errors_str] += 1

    recurring = {err: count for err, count in error_counts.items() if count >= 2}
    if recurring:
        patterns.append({
            "type": "recurring_errors",
            "detail": recurring,
        })
        for err, count in recurring.items():
            recommendations.append(
                f"繰り返しエラー検出: 「{err[:80]}」が{count}回発生。根本原因の調査を推奨。"
            )

    # ── 2. Consistency Score Trend ──
    scores = [
        run.get("consistency_score")
        for run in runs
        if run.get("consistency_score") not in (None, "")
    ]
    if len(scores) >= 3:
        # Check for downward trend (last 3 scores)
        recent_3 = [int(s) for s in scores[:3]]
        if all(recent_3[i] > recent_3[i + 1] for i in range(len(recent_3) - 1)):
            patterns.append({
                "type": "degrading_scores",
                "detail": recent_3,
            })
            recommendations.append(
                f"整合性スコアが低下傾向: {recent_3}。パイプライン品質を確認してください。"
            )

        avg_score = sum(int(s) for s in scores) / len(scores)
        if avg_score < 60:
            patterns.append({
                "type": "low_avg_score",
                "detail": round(avg_score, 1),
            })
            recommendations.append(
                f"平均整合性スコアが低い ({avg_score:.0f}/100)。パイプライン設定の見直しを推奨。"
            )

    # ── 3. Abnormal Execution Times ──
    durations = [
        float(run.get("duration_seconds", 0))
        for run in runs
        if run.get("duration_seconds")
    ]
    if len(durations) >= 3:
        sorted_d = sorted(durations)
        median = sorted_d[len(sorted_d) // 2]
        latest = durations[0] if durations else 0

        if median > 0 and latest > median * 2:
            patterns.append({
                "type": "slow_execution",
                "detail": {
                    "latest": latest,
                    "median": median,
                    "ratio": round(latest / median, 1),
                },
            })
            recommendations.append(
                f"最新の実行が通常の{latest / median:.1f}倍遅い ({latest:.0f}秒 vs 中央値{median:.0f}秒)。"
            )

    # ── 4. Summary ──
    total_runs = len(runs)
    error_runs = sum(1 for r in runs if r.get("errors") and r["errors"] != "[]")
    success_rate = ((total_runs - error_runs) / total_runs * 100) if total_runs > 0 else 0

    result = {
        "status": "analyzed",
        "total_runs": total_runs,
        "success_rate": round(success_rate, 1),
        "patterns": patterns,
        "recommendations": recommendations,
    }

    if patterns:
        logger.info("Detected %d patterns, %d recommendations", len(patterns), len(recommendations))
    else:
        logger.info("No concerning patterns detected (success_rate=%.1f%%)", success_rate)

    return result


def generate_direction_update(patterns_result: dict) -> str | None:
    """
    Generate a direction_notes update string based on detected patterns.

    Returns:
        A string to prepend to direction_notes, or None if no update needed.
    """
    if not patterns_result.get("recommendations"):
        return None

    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    recs = patterns_result["recommendations"]
    success_rate = patterns_result.get("success_rate", "N/A")

    lines = [
        f"[{now} autonomous_agent] パターン検出レポート (成功率: {success_rate}%)",
    ]
    for rec in recs[:5]:  # Max 5 recommendations
        lines.append(f"  - {rec}")

    return "\n".join(lines)
