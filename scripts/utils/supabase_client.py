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


def ensure_business(business_id: str) -> dict[str, Any] | None:
    """Ensure a business exists in the businesses table.

    If the business_id already exists, returns the existing row.
    Otherwise, generates slug + display_name via Gemini API and inserts.
    Returns the business row dict, or None on failure.
    """
    client = get_client()

    # Check if already exists
    result = (
        client.table("businesses")
        .select("*")
        .eq("business_id", business_id)
        .single()
        .execute()
    )
    if result.data:
        logger.info(f"Business already exists: {business_id} → {result.data.get('slug')}")
        return result.data

    # Generate slug and display_name via Gemini
    slug, display_name = _generate_business_meta(business_id)
    if not slug:
        logger.error(f"Failed to generate slug for business: {business_id}")
        return None

    row = {
        "business_id": business_id,
        "slug": slug,
        "display_name": display_name,
        "description": business_id,
        "is_active": True,
    }

    try:
        res = client.table("businesses").insert(row).execute()
        logger.info(f"Registered new business: {business_id} → slug={slug}, name={display_name}")
        return res.data[0] if res.data else row
    except Exception as e:
        logger.error(f"Failed to insert business '{business_id}': {e}")
        return None


def _generate_business_meta(business_id: str) -> tuple[str, str]:
    """Use Gemini to generate a URL slug and short display name for a business.

    Returns (slug, display_name). On failure returns ("", "").
    """
    try:
        from utils.claude_client import generate_json

        result = generate_json(
            prompt=(
                f"以下の事業案名から、WebサイトのURL用の短い英語スラグと、短い日本語表示名を生成してください。\n\n"
                f"事業案名: {business_id}\n\n"
                f"ルール:\n"
                f"- slug: 英小文字とハイフンのみ、2-4単語、URLフレンドリー\n"
                f"- display_name: 日本語、10文字以内、事業の本質を表す短い名前\n\n"
                f"例:\n"
                f'- 入力: "住宅塗装リフォーム向け顧客要望反映型自動見積積算SaaS"\n'
                f'  出力: {{"slug": "tosou-mitsumori", "display_name": "塗装見積もり自動化"}}\n'
                f'- 入力: "塗装資材販売向け塗料使用量予測とコスト自動積算SaaS"\n'
                f'  出力: {{"slug": "tosou-shizai", "display_name": "塗装資材コスト管理"}}\n'
            ),
            system="JSONオブジェクトで出力。slug と display_name の2つのキーのみ。",
            max_tokens=256,
            temperature=0.3,
        )

        if isinstance(result, list):
            result = result[0] if result else {}

        slug = str(result.get("slug", "")).strip().lower()
        display_name = str(result.get("display_name", "")).strip()

        # Validate slug format
        import re
        if not re.match(r"^[a-z][a-z0-9-]{1,50}$", slug):
            # Fallback: simple transliteration
            slug = re.sub(r"[^a-z0-9]+", "-", business_id[:30].lower()).strip("-")[:40]

        if not display_name:
            display_name = business_id[:20]

        return slug, display_name

    except Exception as e:
        logger.error(f"Failed to generate business meta via Gemini: {e}")
        return "", ""
