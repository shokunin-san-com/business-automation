"""
Twitter/X API wrapper using Tweepy.

Error handling:
  - 403 Forbidden: duplicate content, app permissions, or monthly limit
  - 429 Too Many Requests: rate limit (wait and retry)
  - 401 Unauthorized: token expired or invalid
"""
from __future__ import annotations

import re
import time
import tweepy

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    TWITTER_API_KEY,
    TWITTER_API_SECRET,
    TWITTER_ACCESS_TOKEN,
    TWITTER_ACCESS_SECRET,
    get_logger,
)

logger = get_logger(__name__)

_client: tweepy.Client | None = None


def _get_client() -> tweepy.Client:
    global _client
    if _client is None:
        if not all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET]):
            logger.error("Twitter API credentials not configured. Check .env")
            raise RuntimeError("Twitter credentials missing")
        _client = tweepy.Client(
            consumer_key=TWITTER_API_KEY,
            consumer_secret=TWITTER_API_SECRET,
            access_token=TWITTER_ACCESS_TOKEN,
            access_token_secret=TWITTER_ACCESS_SECRET,
        )
        logger.info("Twitter client initialized")
    return _client


def _truncate_for_twitter(text: str) -> str:
    """Truncate text to fit Twitter's 280 character limit."""
    url_pattern = re.compile(r'https?://\S+')
    urls = url_pattern.findall(text)
    twitter_len = len(url_pattern.sub('', text)) + len(urls) * 23
    if twitter_len > 280:
        logger.warning(f"Tweet exceeds 280 Twitter chars ({twitter_len}), truncating")
        text = text[:277] + "..."
    return text


def post_tweet(text: str, max_retries: int = 2) -> dict | None:
    """Post a tweet. Returns response data or None on failure.

    Retries on 429 (rate limit) with exponential backoff.
    Returns detailed error info for diagnosing 403 issues.
    """
    text = _truncate_for_twitter(text)

    try:
        client = _get_client()
    except RuntimeError:
        return None

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.create_tweet(text=text)
            tweet_id = response.data["id"]
            url = f"https://x.com/i/web/status/{tweet_id}"
            logger.info(f"Tweet posted: {url}")
            return {"id": tweet_id, "url": url}

        except tweepy.errors.Forbidden as e:
            error_detail = str(e)
            if "duplicate" in error_detail.lower():
                logger.error(f"Tweet rejected: duplicate content — {error_detail}")
                return {"error": "duplicate", "detail": error_detail}
            elif "limit" in error_detail.lower() or "cap" in error_detail.lower():
                logger.error(f"Tweet rejected: monthly/daily limit — {error_detail}")
                return {"error": "limit_reached", "detail": error_detail}
            else:
                logger.error(
                    f"Tweet 403 Forbidden (attempt {attempt}): {error_detail}\n"
                    f"  Checklist: 1) App has Write permission? "
                    f"2) User auth (not app-only)? "
                    f"3) Free tier monthly limit (1500 tweets)?"
                )
                last_error = e
                break  # 403 is not retryable

        except tweepy.errors.Unauthorized as e:
            logger.error(f"Tweet 401 Unauthorized: {e}. Regenerate tokens in developer.twitter.com")
            return {"error": "unauthorized", "detail": str(e)}

        except tweepy.errors.TooManyRequests as e:
            wait_sec = 30 * attempt
            logger.warning(f"Tweet 429 Rate limit (attempt {attempt}). Waiting {wait_sec}s...")
            time.sleep(wait_sec)
            last_error = e
            continue

        except Exception as e:
            logger.error(f"Tweet unexpected error (attempt {attempt}): {type(e).__name__}: {e}")
            last_error = e
            break

    logger.error(f"Tweet failed after {max_retries} attempts: {last_error}")
    return None
