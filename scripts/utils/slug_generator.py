"""
slug_generator.py — Japanese to URL-safe slug conversion.

Uses Gemini to transliterate Japanese business names into
SEO-friendly URL slugs (e.g., "塗装見積代行" → "tosou-mitsumori-daikou").
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_logger
from utils.claude_client import generate_json_with_retry

logger = get_logger("slug_generator")


def generate_slug(business_name: str) -> str:
    prompt = (
        f"以下の日本語ビジネス名をURL安全なスラッグ（英字ハイフン区切り）に変換してください。\n\n"
        f"ビジネス名: {business_name}\n\n"
        f"ルール:\n"
        f"- ローマ字変換（ヘボン式）\n"
        f"- 単語間はハイフン区切り\n"
        f"- 全て小文字\n"
        f"- 特殊文字なし（英字・数字・ハイフンのみ）\n"
        f"- 30文字以内\n"
        f"- SEOに有利な英語キーワードがあれば混ぜてもよい\n\n"
        f'JSON出力: {{"slug": "tosou-mitsumori"}}'
    )

    try:
        result = generate_json_with_retry(
            prompt=prompt,
            system="URLスラッグを1つだけ生成してください。",
            max_tokens=256,
            temperature=0.1,
            max_retries=1,
        )

        if isinstance(result, list):
            result = result[0] if result else {}

        slug = result.get("slug", "")
        slug = _sanitize_slug(slug)

        if slug:
            return slug
    except Exception as e:
        logger.warning(f"Slug generation failed for '{business_name}': {e}")

    return _fallback_slug(business_name)


def _sanitize_slug(slug: str) -> str:
    slug = slug.lower().strip()
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    if len(slug) > 30:
        slug = slug[:30].rstrip("-")
    return slug


def _fallback_slug(business_name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]", "-", business_name)
    slug = re.sub(r"-+", "-", slug).strip("-").lower()
    if not slug:
        import hashlib
        slug = "biz-" + hashlib.md5(business_name.encode()).hexdigest()[:8]
    return slug[:30]
