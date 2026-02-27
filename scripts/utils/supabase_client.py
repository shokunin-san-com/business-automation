"""
Supabase client for Python scripts (blog_generator, etc.)

Uses service role key to bypass RLS for server-side operations.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_logger

logger = get_logger(__name__)

_client = None


def get_client():
    """Get authenticated Supabase client (cached)."""
    global _client
    if _client is not None:
        return _client

    from supabase import create_client

    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    if not url or not key:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set"
        )

    _client = create_client(url, key)
    logger.info("Supabase client initialized")
    return _client


def upsert_post(post: dict[str, Any]) -> bool:
    """Upsert a post into the posts table.

    Uses (media_id, slug) as the conflict target.
    Returns True on success.
    """
    client = get_client()
    try:
        client.table("posts").upsert(
            post, on_conflict="media_id,slug"
        ).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to upsert post '{post.get('slug', '')}': {e}")
        return False


def upsert_posts(posts: list[dict[str, Any]]) -> int:
    """Upsert multiple posts. Returns count of successful inserts."""
    client = get_client()
    try:
        client.table("posts").upsert(
            posts, on_conflict="media_id,slug"
        ).execute()
        return len(posts)
    except Exception as e:
        logger.error(f"Failed to batch upsert {len(posts)} posts: {e}")
        # Fall back to individual inserts
        success = 0
        for post in posts:
            if upsert_post(post):
                success += 1
        return success


def get_existing_slugs(media_id: str = "shokunin-san") -> set[str]:
    """Get all existing post slugs for a media_id."""
    client = get_client()
    result = (
        client.table("posts")
        .select("slug")
        .eq("media_id", media_id)
        .execute()
    )
    return {r["slug"] for r in (result.data or [])}
