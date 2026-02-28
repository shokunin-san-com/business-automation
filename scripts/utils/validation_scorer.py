"""
validation_scorer.py — Post-launch A/B/C/D rank validation.

Based on email outreach results (2 weeks after launch):
  A: inquiries >= 2 OR replies >= 5 → auto expand targets
  B: inquiries >= 1 OR replies >= 2 → extend 2 weeks
  C: replies >= 1                   → CEO review
  D: replies == 0                   → auto stop

No AI scoring — all metrics from real data sources.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_logger
from utils.sheets_client import get_all_rows, append_rows, get_setting

logger = get_logger("validation_scorer", "validation_scorer.log")

JST = timezone(timedelta(hours=9))


def calculate_validation(
    run_id: str,
    business_id: str,
) -> dict:
    """Calculate A/B/C/D validation rank for a business.

    Reads from mail_sent_log and inquiry_log to determine rank.
    Writes result to validation_score_log.

    Returns:
        {
            "rank": "A" / "B" / "C" / "D",
            "action": "expand" / "extend" / "ceo_review" / "stop",
            "emails_sent": int,
            "replies_received": int,
            "inquiries_received": int,
            "detail": {...},
        }
    """
    # Count emails sent
    try:
        sent_rows = get_all_rows("mail_sent_log")
        biz_sent = [
            r for r in sent_rows
            if r.get("business_id") == business_id
            and r.get("status") == "sent"
        ]
        emails_sent = len(biz_sent)
    except Exception as e:
        logger.warning(f"Failed to read mail_sent_log: {e}")
        biz_sent = []
        emails_sent = 0

    # Count replies (emails with reply status or in inquiry_log)
    replies_received = 0
    try:
        # Check mail_sent_log for bounced/replied status
        for r in sent_rows:
            if r.get("business_id") == business_id and r.get("status") == "replied":
                replies_received += 1
    except Exception:
        pass

    # Count inquiries from inquiry_log
    inquiries_received = 0
    try:
        inquiry_rows = get_all_rows("inquiry_log")
        biz_inquiries = [
            r for r in inquiry_rows
            if r.get("business_id") == business_id
        ]
        inquiries_received = len(biz_inquiries)
    except Exception as e:
        logger.warning(f"Failed to read inquiry_log: {e}")

    # Determine rank
    if inquiries_received >= 2 or replies_received >= 5:
        rank = "A"
        action = "expand"
    elif inquiries_received >= 1 or replies_received >= 2:
        rank = "B"
        action = "extend"
    elif replies_received >= 1:
        rank = "C"
        action = "ceo_review"
    else:
        rank = "D"
        action = "stop"

    detail = {
        "emails_sent": emails_sent,
        "replies_received": replies_received,
        "inquiries_received": inquiries_received,
    }

    # Save to sheet
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    try:
        append_rows("validation_score_log", [[
            run_id,
            business_id,
            now,
            emails_sent,
            replies_received,
            inquiries_received,
            rank,
            action,
            json.dumps(detail, ensure_ascii=False),
        ]])
    except Exception as e:
        logger.warning(f"Failed to save validation score: {e}")

    logger.info(
        f"Validation {business_id}: rank={rank} action={action} "
        f"(sent={emails_sent}, replies={replies_received}, inquiries={inquiries_received})"
    )

    return {
        "rank": rank,
        "action": action,
        "emails_sent": emails_sent,
        "replies_received": replies_received,
        "inquiries_received": inquiries_received,
        "detail": detail,
    }


def run_validation_batch(run_id: str = "") -> list[dict]:
    """Run validation for all businesses that have been sending emails.

    If run_id is specified, only validate that run's businesses.
    """
    period_days = int(get_setting("validation_period_days") or 14)

    try:
        sent_rows = get_all_rows("mail_sent_log")
    except Exception as e:
        logger.error(f"Failed to read mail_sent_log: {e}")
        return []

    # Find distinct business_ids that have sent emails
    cutoff = datetime.now(JST) - timedelta(days=period_days)
    business_ids = set()
    for r in sent_rows:
        if run_id and r.get("run_id") != run_id:
            continue
        sent_at = r.get("sent_at", "")
        if sent_at:
            try:
                dt = datetime.fromisoformat(sent_at.replace(" ", "T"))
                if dt.replace(tzinfo=JST) <= cutoff:
                    business_ids.add(r.get("business_id", ""))
            except (ValueError, TypeError):
                business_ids.add(r.get("business_id", ""))

    if not business_ids:
        logger.info("No businesses ready for validation")
        return []

    results = []
    for biz_id in business_ids:
        if not biz_id:
            continue
        rid = run_id or biz_id
        result = calculate_validation(run_id=rid, business_id=biz_id)
        results.append(result)

    logger.info(f"Validation batch complete: {len(results)} businesses evaluated")
    return results
