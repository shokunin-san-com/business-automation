"""
Learning engine — AI self-learning feedback loop.

Aggregates performance data, detects trends, generates insights,
and provides learning context for prompt injection.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_logger
from utils.claude_client import generate_json
from utils.sheets_client import (
    get_all_rows,
    append_rows,
    ensure_sheet_exists,
)

logger = get_logger("learning_engine", "learning_engine.log")

# Max characters for learning context injection into prompts
MAX_CONTEXT_CHARS = 2000


# ---------------------------------------------------------------------------
# Daily performance aggregation
# ---------------------------------------------------------------------------

def aggregate_daily_performance(target_date: str | None = None) -> list[dict]:
    """Aggregate yesterday's data from analytics/sns_posts/form_sales into performance_log.

    Args:
        target_date: Date string 'YYYY-MM-DD'. Defaults to yesterday.

    Returns:
        List of performance records written.
    """
    if target_date is None:
        target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    ensure_sheet_exists("performance_log", [
        "id", "business_id", "date", "lp_pageviews", "lp_sessions",
        "lp_bounce_rate", "lp_avg_time", "lp_conversions",
        "sns_posts_count", "form_submissions", "form_responses",
        "performance_score", "created_at",
    ])

    # Check if already recorded for this date
    existing = get_all_rows("performance_log")
    existing_dates = {(r.get("business_id", ""), r.get("date", "")) for r in existing}

    # 1. Analytics data
    analytics_rows = get_all_rows("analytics")
    analytics_by_bid: dict[str, dict] = defaultdict(lambda: {
        "pageviews": 0, "sessions": 0, "bounce_rates": [],
        "avg_times": [], "conversions": 0,
    })
    for r in analytics_rows:
        if str(r.get("date", "")).startswith(target_date):
            bid = r.get("business_id", "")
            analytics_by_bid[bid]["pageviews"] += int(r.get("pageviews", 0))
            analytics_by_bid[bid]["sessions"] += int(r.get("sessions", 0))
            analytics_by_bid[bid]["conversions"] += int(r.get("conversions", 0))
            br = r.get("bounce_rate")
            if br:
                analytics_by_bid[bid]["bounce_rates"].append(float(br))
            at = r.get("avg_time")
            if at:
                analytics_by_bid[bid]["avg_times"].append(float(at))

    # 2. SNS posts count
    sns_rows = get_all_rows("sns_posts")
    sns_counts: dict[str, int] = defaultdict(int)
    for r in sns_rows:
        if str(r.get("posted_at", "")).startswith(target_date):
            sns_counts[r.get("business_id", "")] += 1

    # 3. Form sales
    form_rows = get_all_rows("form_sales_targets")
    form_submissions: dict[str, int] = defaultdict(int)
    form_responses: dict[str, int] = defaultdict(int)
    for r in form_rows:
        if str(r.get("contacted_at", "")).startswith(target_date):
            bid = r.get("business_id", "")
            status = r.get("status", "")
            if status in ("success", "sent", "dry_run"):
                form_submissions[bid] += 1
            if status == "success":
                form_responses[bid] += 1

    # Collect all business IDs
    all_bids = set(analytics_by_bid.keys()) | set(sns_counts.keys()) | set(form_submissions.keys())

    records = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    for bid in all_bids:
        if not bid or (bid, target_date) in existing_dates:
            continue

        a = analytics_by_bid.get(bid, {})
        pv = a.get("pageviews", 0) if isinstance(a, dict) else 0
        sess = a.get("sessions", 0) if isinstance(a, dict) else 0
        convs = a.get("conversions", 0) if isinstance(a, dict) else 0
        brs = a.get("bounce_rates", []) if isinstance(a, dict) else []
        ats = a.get("avg_times", []) if isinstance(a, dict) else []

        bounce_rate = round(sum(brs) / len(brs), 1) if brs else 0
        avg_time = round(sum(ats) / len(ats), 1) if ats else 0
        sns_count = sns_counts.get(bid, 0)
        form_sub = form_submissions.get(bid, 0)
        form_resp = form_responses.get(bid, 0)

        # Simple performance score (0-100)
        score = _calculate_score(pv, sess, bounce_rate, avg_time, convs, sns_count, form_sub)

        record_id = f"perf_{bid}_{target_date}"
        records.append([
            record_id, bid, target_date,
            pv, sess, bounce_rate, avg_time, convs,
            sns_count, form_sub, form_resp,
            score, now,
        ])

    if records:
        append_rows("performance_log", records)
        logger.info(f"Recorded performance for {len(records)} businesses on {target_date}")

    return [
        {
            "business_id": r[1], "date": r[2],
            "lp_pageviews": r[3], "lp_sessions": r[4],
            "lp_bounce_rate": r[5], "lp_avg_time": r[6],
            "lp_conversions": r[7], "sns_posts_count": r[8],
            "form_submissions": r[9], "form_responses": r[10],
            "performance_score": r[11],
        }
        for r in records
    ]


def _calculate_score(
    pv: int, sessions: int, bounce_rate: float,
    avg_time: float, conversions: int,
    sns_count: int, form_sub: int,
) -> int:
    """Calculate a simple performance score (0-100)."""
    score = 0
    # PV contribution (max 30 points)
    score += min(pv / 10, 30)
    # Session contribution (max 10 points)
    score += min(sessions / 5, 10)
    # Bounce rate (lower is better, max 15 points)
    if bounce_rate > 0:
        score += max(0, 15 - (bounce_rate / 100) * 15)
    else:
        score += 7  # No data: neutral
    # Avg time (max 15 points, 3+ min is best)
    score += min(avg_time / 180 * 15, 15) if avg_time > 0 else 5
    # Conversions (max 20 points)
    score += min(conversions * 10, 20)
    # Activity (max 10 points)
    score += min((sns_count + form_sub) * 2, 10)

    return min(round(score), 100)


# ---------------------------------------------------------------------------
# Trend detection
# ---------------------------------------------------------------------------

def detect_trends(business_id: str, lookback: int = 14) -> dict:
    """Detect performance trends over recent days.

    Returns:
        {
            "business_id": str,
            "days_analyzed": int,
            "trends": {
                "pageviews": "up" | "down" | "flat",
                "conversions": "up" | "down" | "flat",
                "bounce_rate": "up" | "down" | "flat",
                "score": "up" | "down" | "flat",
            },
            "anomalies": [str],  # Notable changes
            "latest_score": int,
            "avg_score": float,
        }
    """
    rows = get_all_rows("performance_log")
    cutoff = (datetime.now() - timedelta(days=lookback)).strftime("%Y-%m-%d")

    biz_rows = [
        r for r in rows
        if r.get("business_id") == business_id and str(r.get("date", "")) >= cutoff
    ]
    biz_rows.sort(key=lambda r: r.get("date", ""))

    if len(biz_rows) < 2:
        return {
            "business_id": business_id,
            "days_analyzed": len(biz_rows),
            "trends": {},
            "anomalies": [],
            "latest_score": int(biz_rows[-1].get("performance_score", 0)) if biz_rows else 0,
            "avg_score": 0,
        }

    def _trend(values: list[float]) -> str:
        if len(values) < 2:
            return "flat"
        first_half = sum(values[:len(values) // 2]) / max(len(values) // 2, 1)
        second_half = sum(values[len(values) // 2:]) / max(len(values) - len(values) // 2, 1)
        if first_half == 0:
            return "up" if second_half > 0 else "flat"
        change = (second_half - first_half) / first_half
        if change > 0.15:
            return "up"
        elif change < -0.15:
            return "down"
        return "flat"

    pvs = [int(r.get("lp_pageviews", 0)) for r in biz_rows]
    convs = [int(r.get("lp_conversions", 0)) for r in biz_rows]
    brs = [float(r.get("lp_bounce_rate", 0)) for r in biz_rows]
    scores = [int(r.get("performance_score", 0)) for r in biz_rows]

    anomalies = []
    # Detect sudden changes
    if len(scores) >= 3:
        recent = scores[-1]
        prev_avg = sum(scores[:-1]) / len(scores[:-1])
        if prev_avg > 0 and abs(recent - prev_avg) / prev_avg > 0.3:
            direction = "急上昇" if recent > prev_avg else "急低下"
            anomalies.append(f"スコア{direction}: {prev_avg:.0f} → {recent}")

    if len(pvs) >= 3:
        recent_pv = pvs[-1]
        prev_avg_pv = sum(pvs[:-1]) / len(pvs[:-1])
        if prev_avg_pv > 0 and abs(recent_pv - prev_avg_pv) / prev_avg_pv > 0.5:
            direction = "急増" if recent_pv > prev_avg_pv else "急減"
            anomalies.append(f"PV{direction}: {prev_avg_pv:.0f} → {recent_pv}")

    return {
        "business_id": business_id,
        "days_analyzed": len(biz_rows),
        "trends": {
            "pageviews": _trend([float(x) for x in pvs]),
            "conversions": _trend([float(x) for x in convs]),
            "bounce_rate": _trend(brs),
            "score": _trend([float(x) for x in scores]),
        },
        "anomalies": anomalies,
        "latest_score": scores[-1] if scores else 0,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
    }


# ---------------------------------------------------------------------------
# AI insight generation
# ---------------------------------------------------------------------------

def generate_insights(
    performance: list[dict],
    trends: list[dict],
) -> list[dict]:
    """Use AI to generate learning insights from performance data and trends.

    Args:
        performance: List of daily performance records.
        trends: List of trend analysis results per business.

    Returns:
        List of insight dicts saved to learning_memory.
    """
    if not performance and not trends:
        logger.info("No performance/trend data — skipping insight generation")
        return []

    from jinja2 import Environment, FileSystemLoader
    from config import TEMPLATES_DIR

    jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = jinja_env.get_template("learning_analysis_prompt.j2")

    prompt = template.render(
        performance=performance,
        trends=trends,
        today=datetime.now().strftime("%Y-%m-%d"),
    )

    try:
        insights = generate_json(
            prompt=prompt,
            system="あなたはデジタルマーケティングと事業検証の分析AIです。過去のデータから教訓を抽出し、今後の改善に活かせるインサイトを生成してください。",
            max_tokens=2048,
            temperature=0.5,
        )
    except Exception as e:
        logger.error(f"Insight generation failed: {e}")
        return []

    if isinstance(insights, dict):
        insights = insights.get("insights", [insights])
    if not isinstance(insights, list):
        insights = [insights]

    return _save_insights(insights)


def _save_insights(insights: list[dict]) -> list[dict]:
    """Save generated insights to learning_memory sheet."""
    ensure_sheet_exists("learning_memory", [
        "id", "type", "source", "category", "content",
        "context_json", "confidence", "priority", "status",
        "applied_count", "created_at", "expires_at",
    ])

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    expires = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    rows = []
    saved = []

    from utils.ceo_profile import is_ceo_profile_enabled
    source_mode = "ceo_profile" if is_ceo_profile_enabled() else "neutral"

    for ins in insights:
        content = ins.get("content", ins.get("insight", ""))
        if not content:
            continue

        insight_id = f"ins_{uuid.uuid4().hex[:8]}"
        category = ins.get("category", "general")
        priority = ins.get("priority", "medium")
        confidence = ins.get("confidence", 0.7)
        ctx = ins.get("context", {})
        ctx["source_mode"] = source_mode
        context = json.dumps(ctx, ensure_ascii=False)
        insight_type = ins.get("type", "insight")

        rows.append([
            insight_id, insight_type, "ai_analysis", category,
            content, context, confidence, priority,
            "active", 0, now, expires,
        ])
        saved.append({
            "id": insight_id,
            "type": insight_type,
            "category": category,
            "content": content,
            "priority": priority,
        })

    if rows:
        append_rows("learning_memory", rows)
        logger.info(f"Saved {len(rows)} insights to learning_memory")

    return saved


# ---------------------------------------------------------------------------
# Learning context for prompt injection
# ---------------------------------------------------------------------------

def _get_source_mode(row: dict) -> str:
    """Extract source_mode from context_json."""
    try:
        ctx = json.loads(row.get("context_json", "{}"))
        return ctx.get("source_mode", "")
    except (json.JSONDecodeError, TypeError):
        return ""


def get_learning_context(
    categories: list[str] | None = None,
    limit: int = 10,
) -> str:
    """Get active learning memories formatted for prompt injection.

    Args:
        categories: Filter by category (e.g. ['lp_optimization', 'general']).
                    None means all categories.
        limit: Max number of entries to include.

    Returns:
        Formatted text string for injection into AI prompts.
        Empty string if no relevant memories.
    """
    try:
        rows = get_all_rows("learning_memory")
    except Exception:
        return ""

    if not rows:
        return ""

    # Filter active entries
    active = [r for r in rows if r.get("status") == "active"]

    # Filter by categories
    if categories:
        active = [r for r in active if r.get("category") in categories or r.get("category") == "general"]

    # Filter out expired
    today = datetime.now().strftime("%Y-%m-%d")
    active = [
        r for r in active
        if not r.get("expires_at") or str(r.get("expires_at", "")) >= today
    ]

    # Filter by source_mode to avoid cross-contamination
    from utils.ceo_profile import is_ceo_profile_enabled
    current_mode = "ceo_profile" if is_ceo_profile_enabled() else "neutral"
    active = [
        r for r in active
        if _get_source_mode(r) in (current_mode, "neutral", "")
    ]

    if not active:
        return ""

    # Sort by priority (high > medium > low) then by confidence desc
    priority_order = {"high": 0, "medium": 1, "low": 2}
    active.sort(key=lambda r: (
        priority_order.get(r.get("priority", "medium"), 1),
        -float(r.get("confidence", 0)),
    ))

    # Take top entries
    active = active[:limit]

    # Format for prompt injection
    parts = []
    for r in active:
        source_label = "AI分析" if r.get("source") == "ai_analysis" else "運用者指示"
        priority_label = {"high": "高", "medium": "中", "low": "低"}.get(
            r.get("priority", "medium"), "中"
        )
        entry = f"- [{source_label}/{priority_label}] {r.get('content', '')}"
        parts.append(entry)

    result = "\n".join(parts)

    # Truncate if too long
    if len(result) > MAX_CONTEXT_CHARS:
        result = result[:MAX_CONTEXT_CHARS].rsplit("\n", 1)[0]

    return result


# ---------------------------------------------------------------------------
# Human directive (from chat feedback)
# ---------------------------------------------------------------------------

def save_human_directive(
    content: str,
    category: str = "general",
    priority: str = "high",
) -> dict:
    """Save a human directive from the feedback chat.

    Human directives have confidence=1.0 and no expiry.

    Args:
        content: The directive text.
        category: One of lp_optimization, sns_strategy, form_sales,
                  idea_generation, general.
        priority: high, medium, low.

    Returns:
        The saved directive record.
    """
    ensure_sheet_exists("learning_memory", [
        "id", "type", "source", "category", "content",
        "context_json", "confidence", "priority", "status",
        "applied_count", "created_at", "expires_at",
    ])

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    directive_id = f"dir_{uuid.uuid4().hex[:8]}"

    row = [
        directive_id, "directive", "human_chat", category,
        content, "{}", 1.0, priority,
        "active", 0, now, "",  # No expiry for human directives
    ]
    append_rows("learning_memory", [row])
    logger.info(f"Saved human directive: {directive_id} [{category}]")

    return {
        "id": directive_id,
        "type": "directive",
        "category": category,
        "content": content,
        "priority": priority,
    }


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------

def expire_old_insights(max_age_days: int = 30) -> int:
    """Mark expired insights as 'expired'.

    Returns the number of entries expired.
    """
    from utils.sheets_client import find_row_index, get_worksheet

    rows = get_all_rows("learning_memory")
    today = datetime.now().strftime("%Y-%m-%d")
    expired_count = 0

    ws = get_worksheet("learning_memory")
    headers = ws.row_values(1)
    status_col = headers.index("status") + 1 if "status" in headers else None

    if not status_col:
        return 0

    for r in rows:
        if r.get("status") != "active":
            continue
        expires = r.get("expires_at", "")
        if expires and str(expires) < today:
            row_idx = find_row_index("learning_memory", "id", r.get("id", ""))
            if row_idx:
                ws.update_cell(row_idx, status_col, "expired")
                expired_count += 1

    if expired_count:
        logger.info(f"Expired {expired_count} old insights")

    return expired_count


def get_performance_summary(business_id: str | None = None, days: int = 7) -> str:
    """Get a formatted performance summary for chat context.

    Args:
        business_id: Optional filter. None returns all businesses.
        days: Number of days to look back.

    Returns:
        Formatted text summary.
    """
    rows = get_all_rows("performance_log")
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    filtered = [
        r for r in rows
        if str(r.get("date", "")) >= cutoff
    ]
    if business_id:
        filtered = [r for r in filtered if r.get("business_id") == business_id]

    if not filtered:
        return "パフォーマンスデータなし"

    # Group by business_id
    by_bid: dict[str, list] = defaultdict(list)
    for r in filtered:
        by_bid[r.get("business_id", "")].append(r)

    parts = []
    for bid, records in by_bid.items():
        records.sort(key=lambda r: r.get("date", ""))
        latest = records[-1]
        avg_score = sum(int(r.get("performance_score", 0)) for r in records) / len(records)

        part = (
            f"### {bid}\n"
            f"期間: {records[0].get('date', '')} ~ {records[-1].get('date', '')}\n"
            f"最新スコア: {latest.get('performance_score', 0)} / 平均: {avg_score:.0f}\n"
            f"PV: {latest.get('lp_pageviews', 0)} / セッション: {latest.get('lp_sessions', 0)} / "
            f"CVR: {latest.get('lp_conversions', 0)} / 直帰率: {latest.get('lp_bounce_rate', 0)}%\n"
            f"SNS: {latest.get('sns_posts_count', 0)}件 / フォーム: {latest.get('form_submissions', 0)}件"
        )
        parts.append(part)

    return "\n\n".join(parts)
