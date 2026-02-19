"""
Twitter/X API wrapper using Tweepy.
"""

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
        _client = tweepy.Client(
            consumer_key=TWITTER_API_KEY,
            consumer_secret=TWITTER_API_SECRET,
            access_token=TWITTER_ACCESS_TOKEN,
            access_token_secret=TWITTER_ACCESS_SECRET,
        )
        logger.info("Twitter client initialized")
    return _client


def post_tweet(text: str) -> dict | None:
    """Post a tweet. Returns response data or None on failure.

    Text is truncated to 280 characters.
    """
    if len(text) > 280:
        text = text[:277] + "..."
        logger.warning("Tweet text truncated to 280 chars")

    client = _get_client()
    try:
        response = client.create_tweet(text=text)
        tweet_id = response.data["id"]
        url = f"https://x.com/i/web/status/{tweet_id}"
        logger.info(f"Tweet posted: {url}")
        return {"id": tweet_id, "url": url}
    except Exception as e:
        logger.error(f"Failed to post tweet: {e}")
        return None
