"""
validation_scorer.py — Post-launch validation metrics.

Measures actual market performance after LP launch:
  1. LP page views (from GA4 or status_log)
  2. Form submission rate
  3. SNS engagement metrics
  4. Form sales response rate

Outputs to validation_score_log. Used by orchestrate_v2 to decide
whether to continue investing in a market or pivot.

No AI scoring — all metrics from real data sources.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_logger
from utils.sheets_client import get_all_rows, append_rows, ensure_sheet_exists

logger = get_logger("validation_scorer", "validation_scorer.log")

VALIDATION_SHEET = "validation_score_log"
VALIDATION_HEADERS = [
    "run_id", "business_id", "market_name",
    "lp_views", "form_submissions", "form_rate_pct",
    "sns_posts", "sns_engagements",
    "form_sales_sent", "form_sales_replied", "reply_rate_pct",
    "validation_status", "scored_at",
]

# Validation thresholds (Phase 4 criteria)
MIN_LP_VIEWS_7D = 50         # Minimum LP views in 7 days
MIN_FORM_RATE_PCT = 2.0      # Minimum form submission rate %
MIN_FORM_SALES_SENT = 10     # Minimum form sales attempts
MIN_REPLY_RATE_PCT = 1.0     # Minimum reply rate from form sales


def _count_by_field(rows: list[dict], field: str, value: str) -> int:
    """Count rows where field matches value."""
    return sum(1 for r in rows if r.get(field) == value)


def _count_by_prefix(rows: list[dict], field: str, prefix: str) -> int:
    """Count rows where field starts with prefix."""
    return sum(1 for r in rows if str(r.get(field, "")).startswith(prefix))


def calculate_validation(
    run_id: str,
    business_id: str,
    market_name: str = "",
) -> dict:
    """Calculate validation metrics for a launched market.

    Aggregates data from multiple sheets:
    - lp_ready_log: LP status
    - form_sales_log: form submission data
    - sns_queue: SNS posting data
    - status_log: LP view counts (from GA4 integration)
    """
    ensure_sheet_exists(VALIDATION_SHEET, VALIDATION_HEADERS)

    metrics = {
        "lp_views": 0,
        "form_submissions": 0,
        "form_rate_pct": 0.0,
        "sns_posts": 0,
        "sns_engagements": 0,
        "form_sales_sent": 0,
        "form_sales_replied": 0,
        "reply_rate_pct": 0.0,
    }

    # LP views from status_log (GA4 data if available)
    try:
        status_rows = get_all_rows("status_log")
        for r in status_rows:
            if r.get("script_name") == "ga4_reporter" and business_id in str(r.get("detail", "")):
                try:
                    detail = json.loads(r.get("detail", "{}"))
                    metrics["lp_views"] += int(detail.get("page_views", 0))
                except (json.JSONDecodeError, ValueError):
                    pass
    except Exception as e:
        logger.warning(f"Failed to read LP views: {e}")

    # Form sales data
    try:
        form_rows = get_all_rows("form_sales_log")
        biz_forms = [r for r in form_rows if business_id in str(r.get("business_id", ""))]
        metrics["form_sales_sent"] = len(biz_forms)
        metrics["form_sales_replied"] = sum(
            1 for r in biz_forms if r.get("status") == "replied"
        )
        metrics["form_submissions"] = sum(
            1 for r in biz_forms if r.get("status") in ("sent", "replied", "success")
        )
    except Exception as e:
        logger.warning(f"Failed to read form sales data: {e}")

    # SNS metrics
    try:
        sns_rows = get_all_rows("sns_queue")
        biz_sns = [r for r in sns_rows if business_id in str(r.get("business_id", ""))]
        metrics["sns_posts"] = sum(1 for r in biz_sns if r.get("status") == "posted")
        # Engagement is tracked separately if available
        metrics["sns_engagements"] = sum(
            int(r.get("engagement_count", 0) or 0) for r in biz_sns
        )
    except Exception as e:
        logger.warning(f"Failed to read SNS data: {e}")

    # Calculate rates
    if metrics["lp_views"] > 0:
        metrics["form_rate_pct"] = round(
            metrics["form_submissions"] / metrics["lp_views"] * 100, 2
        )
    if metrics["form_sales_sent"] > 0:
        metrics["reply_rate_pct"] = round(
            metrics["form_sales_replied"] / metrics["form_sales_sent"] * 100, 2
        )

    # Validation decision
    passes = []
    fails = []

    if metrics["lp_views"] >= MIN_LP_VIEWS_7D:
        passes.append("LP閲覧数OK")
    else:
        fails.append(f"LP閲覧{metrics['lp_views']}件 < {MIN_LP_VIEWS_7D}")

    if metrics["form_rate_pct"] >= MIN_FORM_RATE_PCT:
        passes.append("フォーム率OK")
    elif metrics["lp_views"] > 0:
        fails.append(f"フォーム率{metrics['form_rate_pct']}% < {MIN_FORM_RATE_PCT}%")

    if metrics["form_sales_sent"] >= MIN_FORM_SALES_SENT:
        if metrics["reply_rate_pct"] >= MIN_REPLY_RATE_PCT:
            passes.append("返信率OK")
        else:
            fails.append(f"返信率{metrics['reply_rate_pct']}% < {MIN_REPLY_RATE_PCT}%")

    # Status: VALIDATED (all pass), PARTIAL (some pass), INSUFFICIENT (no data)
    if len(passes) >= 2 and not fails:
        status = "VALIDATED"
    elif passes:
        status = "PARTIAL"
    elif metrics["lp_views"] == 0 and metrics["form_sales_sent"] == 0:
        status = "INSUFFICIENT"
    else:
        status = "FAILED"

    metrics["validation_status"] = status

    # Save to sheet
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    append_rows(VALIDATION_SHEET, [[
        run_id,
        business_id,
        market_name,
        metrics["lp_views"],
        metrics["form_submissions"],
        metrics["form_rate_pct"],
        metrics["sns_posts"],
        metrics["sns_engagements"],
        metrics["form_sales_sent"],
        metrics["form_sales_replied"],
        metrics["reply_rate_pct"],
        status,
        now,
    ]])

    logger.info(
        f"Validation for {business_id}: {status} "
        f"(views={metrics['lp_views']}, form_rate={metrics['form_rate_pct']}%, "
        f"reply_rate={metrics['reply_rate_pct']}%)"
    )

    return metrics
