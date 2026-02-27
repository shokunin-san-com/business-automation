"""
migrate_blog_to_supabase.py — Migrate existing blog articles from Google Sheets to Supabase.

One-time migration script. Run after Supabase project is created and tables exist.

Usage:
  python scripts/migrate_blog_to_supabase.py

Requires env vars:
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, GOOGLE_SERVICE_ACCOUNT_JSON
"""

import sys
import json
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_logger
from utils.sheets_client import get_all_rows
from utils.supabase_client import get_client

logger = get_logger("migrate_blog", "migrate_blog.log")

MEDIA_ID = "shokunin-san"


def strip_inline_cta(html: str) -> str:
    """Remove inline CTA divs that were embedded by earlier blog_generator."""
    return re.sub(
        r'<div style="margin-top:2em;padding:1\.5em;background:#eff6ff[^"]*"[^>]*>[\s\S]*?</div>\s*$',
        "",
        html,
    )


def migrate():
    logger.info("=== Blog migration: Sheets → Supabase ===")

    rows = get_all_rows("blog_articles")
    logger.info(f"Found {len(rows)} articles in Sheets")

    if not rows:
        logger.info("No articles to migrate")
        return

    client = get_client()
    migrated = 0
    skipped = 0
    errors = 0

    for row in rows:
        slug = row.get("slug", "")
        if not slug:
            skipped += 1
            continue

        # Parse tags
        tags_raw = row.get("tags", "[]")
        if isinstance(tags_raw, str):
            try:
                tags = json.loads(tags_raw)
            except (json.JSONDecodeError, ValueError):
                tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        elif isinstance(tags_raw, list):
            tags = tags_raw
        else:
            tags = []

        body_html = strip_inline_cta(str(row.get("body_html", "")))

        post = {
            "business_id": str(row.get("business_id", "")),
            "media_id": MEDIA_ID,
            "title": str(row.get("title", "")),
            "slug": slug,
            "body_html": body_html,
            "excerpt": str(row.get("excerpt", "")),
            "category": str(row.get("category", "")),
            "tags": tags,
            "meta_description": str(row.get("meta_description", "")),
            "og_title": str(row.get("og_title", row.get("title", ""))),
            "og_description": str(row.get("og_description", row.get("meta_description", ""))),
            "status": str(row.get("status", "published")),
            "published_at": str(row.get("published_at", "")) or None,
            "generated_at": str(row.get("generated_at", "")) or None,
        }

        try:
            client.table("posts").upsert(
                post, on_conflict="media_id,slug"
            ).execute()
            migrated += 1
            if migrated % 10 == 0:
                logger.info(f"  Migrated {migrated} articles...")
        except Exception as e:
            logger.error(f"Failed to migrate '{slug}': {e}")
            errors += 1

    logger.info(
        f"=== Migration complete: {migrated} migrated, {skipped} skipped, {errors} errors ==="
    )


if __name__ == "__main__":
    migrate()
