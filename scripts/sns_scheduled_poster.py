"""
sns_scheduled_poster.py — Post queued SNS posts from sns_queue.

Reads queued posts, evaluates risk, posts to Twitter/LinkedIn,
and updates status. Designed to run on Cloud Scheduler (every 3 hours).
"""

import sys
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_logger
from utils.sheets_client import get_all_rows, update_cell
from utils.twitter_client import post_tweet
from utils.linkedin_client import post_text as post_linkedin
from utils.risk_scorer import evaluate as evaluate_risk
from utils.slack_notifier import send_message as slack_notify
from utils.status_writer import update_status

logger = get_logger("sns_scheduled_poster", "sns_scheduled_poster.log")

MAX_POSTS_PER_RUN = 5        # Max posts per execution
POST_INTERVAL_SEC = 30        # Seconds between posts (rate limit safety)
MAX_TWITTER_PER_RUN = 3
MAX_LINKEDIN_PER_RUN = 2


def _get_queued_posts() -> list[dict]:
    """Get all queued posts from sns_queue, oldest first."""
    rows = get_all_rows("sns_queue")
    queued = [r for r in rows if r.get("status") == "queued"]
    # Sort by queue_id (oldest first)
    queued.sort(key=lambda r: r.get("queue_id", ""))
    return queued


def _post_to_platform(text: str, platform: str) -> tuple[str, str]:
    """Post text to platform. Returns (status, url)."""
    try:
        if platform == "twitter":
            result = post_tweet(text)
        elif platform == "linkedin":
            result = post_linkedin(text)
        else:
            return "failed", ""

        if result is None:
            return "failed", ""

        url = result.get("url", "") or result.get("id", "")
        return "posted", url
    except Exception as e:
        logger.error(f"Post to {platform} failed: {e}")
        return "failed", str(e)


def main():
    logger.info("=== SNS scheduled poster start ===")
    update_status("sns_scheduled_poster", "running", "キュー投稿処理中...")

    try:
        queued = _get_queued_posts()
        if not queued:
            logger.info("No queued posts. Exiting.")
            update_status("sns_scheduled_poster", "success", "キュー空")
            return

        logger.info(f"Found {len(queued)} queued posts")

        twitter_count = 0
        linkedin_count = 0
        total_posted = 0
        total_failed = 0
        total_skipped = 0

        for post in queued:
            if total_posted + total_failed + total_skipped >= MAX_POSTS_PER_RUN:
                break

            platform = post.get("platform", "twitter")
            queue_id = post.get("queue_id", "")
            text = post.get("post_text", "")

            # Enforce per-platform limits
            if platform == "twitter" and twitter_count >= MAX_TWITTER_PER_RUN:
                continue
            if platform == "linkedin" and linkedin_count >= MAX_LINKEDIN_PER_RUN:
                continue

            if not text:
                update_cell("sns_queue", "queue_id", queue_id, "status", "skipped")
                update_cell("sns_queue", "queue_id", queue_id, "error_detail", "empty text")
                total_skipped += 1
                continue

            # Risk evaluation (skip AI to save cost/time)
            risk = evaluate_risk(
                text=text,
                platform=platform,
                context=f"Queued SNS post {queue_id}",
                use_ai=False,
            )

            now = datetime.now().strftime("%Y-%m-%d %H:%M")

            if risk.decision == "block":
                logger.warning(f"Post {queue_id} blocked (risk={risk.score}): {risk.detail}")
                update_cell("sns_queue", "queue_id", queue_id, "status", "skipped")
                update_cell("sns_queue", "queue_id", queue_id, "error_detail", f"risk_blocked: {risk.detail}")
                total_skipped += 1
                continue

            # Post it
            logger.info(f"Posting {queue_id} to {platform} (risk={risk.score})")
            status, url_or_error = _post_to_platform(text, platform)

            update_cell("sns_queue", "queue_id", queue_id, "status", status)
            update_cell("sns_queue", "queue_id", queue_id, "posted_at", now)

            if status == "posted":
                update_cell("sns_queue", "queue_id", queue_id, "post_url", url_or_error)
                total_posted += 1
                if platform == "twitter":
                    twitter_count += 1
                else:
                    linkedin_count += 1
                logger.info(f"  → Posted: {url_or_error}")
            else:
                update_cell("sns_queue", "queue_id", queue_id, "error_detail", url_or_error)
                total_failed += 1
                logger.error(f"  → Failed: {url_or_error}")

            # Rate limit safety
            time.sleep(POST_INTERVAL_SEC)

        # Summary
        remaining = len(queued) - total_posted - total_failed - total_skipped
        summary = f"投稿{total_posted}件 / 失敗{total_failed}件 / スキップ{total_skipped}件 / 残{remaining}件"

        if total_posted > 0:
            slack_notify(f":mega: SNSスケジュール投稿: {summary}")

        update_status("sns_scheduled_poster", "success", summary, {
            "posted": total_posted,
            "failed": total_failed,
            "skipped": total_skipped,
            "remaining": remaining,
        })
        logger.info(f"=== SNS scheduled poster complete: {summary} ===")

    except Exception as e:
        update_status("sns_scheduled_poster", "error", str(e))
        logger.error(f"SNS scheduled poster failed: {e}")
        raise


if __name__ == "__main__":
    main()
