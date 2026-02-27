"""
sns_scheduled_poster.py — Post queued SNS posts from sns_queue.

Reads queued posts, evaluates risk, posts to Twitter/LinkedIn,
and updates status. Designed to run on Cloud Scheduler (every 3 hours).

Daily limits: Twitter 2/day, LinkedIn 2/day.
"""

import sys
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_logger
from utils.sheets_client import get_all_rows, batch_update_by_key
from utils.twitter_client import post_tweet
from utils.linkedin_client import post_text as post_linkedin
from utils.risk_scorer import evaluate as evaluate_risk
from utils.slack_notifier import send_message as slack_notify
from utils.status_writer import update_status

logger = get_logger("sns_scheduled_poster", "sns_scheduled_poster.log")

MAX_POSTS_PER_RUN = 4         # Max posts per execution
POST_INTERVAL_SEC = 30        # Seconds between posts (rate limit safety)
DAILY_TWITTER_LIMIT = 2       # X(Twitter): 2 posts/day
DAILY_LINKEDIN_LIMIT = 2      # LinkedIn: 2 posts/day


def _count_today_posted(all_rows: list[dict], platform: str) -> int:
    """Count how many posts were already posted today for a platform."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    count = 0
    for r in all_rows:
        if (r.get("status") == "posted"
                and r.get("platform") == platform
                and str(r.get("posted_at", "")).startswith(today_str)):
            count += 1
    return count


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
        # Single API call to get all rows (reused for daily count + queued filtering)
        all_rows = get_all_rows("sns_queue")

        queued = [r for r in all_rows if r.get("status") == "queued"]
        queued.sort(key=lambda r: r.get("queue_id", ""))

        if not queued:
            logger.info("No queued posts. Exiting.")
            update_status("sns_scheduled_poster", "success", "キュー空")
            return

        logger.info(f"Found {len(queued)} queued posts")

        # Check daily limits (already posted today)
        twitter_today = _count_today_posted(all_rows, "twitter")
        linkedin_today = _count_today_posted(all_rows, "linkedin")
        logger.info(f"Today's posts: Twitter={twitter_today}/{DAILY_TWITTER_LIMIT}, LinkedIn={linkedin_today}/{DAILY_LINKEDIN_LIMIT}")

        twitter_remaining = max(0, DAILY_TWITTER_LIMIT - twitter_today)
        linkedin_remaining = max(0, DAILY_LINKEDIN_LIMIT - linkedin_today)

        if twitter_remaining == 0 and linkedin_remaining == 0:
            logger.info("Daily limits reached for all platforms. Exiting.")
            update_status("sns_scheduled_poster", "success", "本日の投稿上限到達")
            return

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

            # Enforce daily platform limits
            if platform == "twitter" and twitter_count >= twitter_remaining:
                continue
            if platform == "linkedin" and linkedin_count >= linkedin_remaining:
                continue

            if not text:
                batch_update_by_key("sns_queue", "queue_id", queue_id, {
                    "status": "skipped",
                    "error_detail": "empty text",
                })
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
                batch_update_by_key("sns_queue", "queue_id", queue_id, {
                    "status": "skipped",
                    "error_detail": f"risk_blocked: {risk.detail}",
                })
                total_skipped += 1
                continue

            # Post it
            logger.info(f"Posting {queue_id} to {platform} (risk={risk.score})")
            status, url_or_error = _post_to_platform(text, platform)

            if status == "posted":
                batch_update_by_key("sns_queue", "queue_id", queue_id, {
                    "status": status,
                    "posted_at": now,
                    "post_url": url_or_error,
                })
                total_posted += 1
                if platform == "twitter":
                    twitter_count += 1
                else:
                    linkedin_count += 1
                logger.info(f"  → Posted: {url_or_error}")
            else:
                batch_update_by_key("sns_queue", "queue_id", queue_id, {
                    "status": status,
                    "posted_at": now,
                    "error_detail": url_or_error,
                })
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
