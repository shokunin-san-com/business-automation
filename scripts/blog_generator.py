"""
blog_generator.py — Generate 50 SEO blog articles for a target market.

Generates articles across 10 categories (5 per category),
stores in Supabase posts table (primary) and blog_articles sheet (fallback).
Auto-assigns cover images from Supabase Storage pool.

Can be called directly via CLI or imported by 1_lp_generator.py.
"""

import sys
import os
import uuid
import json
import random
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import TEMPLATES_DIR, get_logger
from utils.claude_client import generate_json_with_retry
from utils.sheets_client import get_all_rows, append_rows
from utils.gcs_client import upload_json as gcs_upload
from utils.slack_notifier import send_message as slack_notify

logger = get_logger("blog_generator", "blog_generator.log")

jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

LP_BASE_URL = "https://shokunin-san.xyz"
DEFAULT_MEDIA_ID = "shokunin-san"

# 10 universal category types (labels are generated dynamically per market)
CATEGORY_KEYS = [
    "industry_challenges",
    "howto",
    "comparison",
    "case_study",
    "trend",
    "qa",
    "checklist",
    "glossary",
    "management",
    "seo_longtail",
]

CATEGORY_LABELS_DEFAULT = {
    "industry_challenges": "業界課題解説",
    "howto": "ハウツー",
    "comparison": "比較記事",
    "case_study": "事例紹介",
    "trend": "トレンド",
    "qa": "Q&A",
    "checklist": "チェックリスト",
    "glossary": "用語解説",
    "management": "経営者向け",
    "seo_longtail": "SEOロングテール",
}


def _generate_topics(market_name: str, payer: str, offers: list[dict]) -> dict:
    """Generate market-specific topics via AI. Returns {cat_key: {label, topics[]}}."""
    offers_text = ""
    for i, o in enumerate(offers[:3], 1):
        offers_text += f"  {i}. {o.get('offer_name', '')} — {o.get('deliverable', '')}\n"

    prompt = f"""以下の事業に最適な、SEOブログ記事のトピック案を生成してください。

## 事業情報
- 事業名: {market_name}
- ターゲット顧客: {payer or '経営者・意思決定者'}
- 提供サービス:
{offers_text or '  （AI業務自動化SaaS）'}

## 要件
10カテゴリ × 5トピック = 合計50トピックを生成してください。
各トピックはSEOで上位表示を狙える、具体的で実用的なタイトル案にしてください。
ターゲット顧客が検索しそうなキーワードを自然に含めてください。

## カテゴリ一覧（各5トピック）
1. industry_challenges — 業界の課題や問題点を解説
2. howto — 実践的なノウハウ・テクニック
3. comparison — ツール比較・手法比較
4. case_study — 導入事例・成功事例（架空の固有名詞は不可）
5. trend — 業界トレンド・最新動向
6. qa — よくある質問・Q&A
7. checklist — チェックリスト・手順書
8. glossary — 専門用語・基礎知識の解説
9. management — 経営者・意思決定者向けの記事
10. seo_longtail — ロングテールSEO狙いの記事

## 出力形式
JSONオブジェクトで返してください:
{{
  "industry_challenges": {{
    "label": "（この事業に合ったカテゴリ表示名）",
    "topics": ["トピック1", "トピック2", "トピック3", "トピック4", "トピック5"]
  }},
  "howto": {{
    "label": "...",
    "topics": ["...", "...", "...", "...", "..."]
  }},
  ...（10カテゴリすべて）
}}"""

    logger.info("Generating market-specific topics via AI...")
    result = generate_json_with_retry(
        prompt=prompt,
        system="あなたはBtoB SEOストラテジストです。指定のJSONフォーマットで正確に出力してください。",
        max_tokens=8192,
        temperature=0.7,
        max_retries=3,
    )

    if isinstance(result, list):
        result = result[0] if result else {}

    # Validate: ensure all 10 categories with 5 topics each
    validated = {}
    for key in CATEGORY_KEYS:
        cat = result.get(key, {})
        if not isinstance(cat, dict):
            cat = {}
        label = cat.get("label", CATEGORY_LABELS_DEFAULT.get(key, key))
        topics = cat.get("topics", [])
        if not isinstance(topics, list) or len(topics) < 5:
            logger.warning(f"Category '{key}' has {len(topics) if isinstance(topics, list) else 0} topics, padding with defaults")
            # Pad with generic topics
            while len(topics) < 5:
                topics.append(f"{market_name}における{label}の重要ポイント（{len(topics)+1}）")
        validated[key] = {"label": label, "topics": topics[:5]}

    total = sum(len(v["topics"]) for v in validated.values())
    logger.info(f"Generated {total} topics across {len(validated)} categories")
    return validated


def _assign_cover_images(business_id: str, media_id: str) -> int:
    """Auto-assign cover images from Supabase Storage pool to posts without images."""
    try:
        from supabase import create_client

        # Load Supabase credentials
        env_path = Path(__file__).resolve().parent.parent / "lp-app" / ".env.local"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())

        url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        if not url or not key:
            logger.warning("Supabase credentials not available for cover image assignment")
            return 0

        client = create_client(url, key)

        # List available eyecatch images from storage
        bucket = client.storage.from_("blog-images")
        files = bucket.list("eyecatch")
        if not files:
            logger.info("No eyecatch images in storage pool")
            return 0

        image_urls = [
            f"{url}/storage/v1/object/public/blog-images/eyecatch/{f['name']}"
            for f in files
            if f.get("name") and not f["name"].startswith(".")
        ]
        if not image_urls:
            return 0

        logger.info(f"Found {len(image_urls)} eyecatch images in pool")

        # Get posts without cover_image for this business
        result = (
            client.table("posts")
            .select("id, slug, cover_image")
            .eq("business_id", business_id)
            .eq("media_id", media_id)
            .eq("status", "published")
            .order("published_at", desc=False)
            .execute()
        )
        posts = result.data or []
        needs_image = [p for p in posts if not p.get("cover_image")]

        if not needs_image:
            logger.info("All posts already have cover images")
            return 0

        # Shuffle images for variety
        random.seed(hash(business_id) % (2**31))
        random.shuffle(image_urls)

        updated = 0
        for i, post in enumerate(needs_image):
            img_url = image_urls[i % len(image_urls)]
            try:
                client.table("posts").update({"cover_image": img_url}).eq("id", post["id"]).execute()
                updated += 1
            except Exception as e:
                logger.warning(f"Failed to assign image to {post['slug']}: {e}")

        logger.info(f"Assigned cover images to {updated}/{len(needs_image)} posts")
        return updated

    except Exception as e:
        logger.warning(f"Cover image assignment failed: {e}")
        return 0


def _get_market_info(business_id: str) -> dict:
    """Get market details for the target business."""
    gates = get_all_rows("gate_decision_log")
    gate = None
    for g in gates:
        if g.get("status") == "PASS" and business_id in g.get("micro_market", ""):
            gate = g
            break

    offers = get_all_rows("offer_3_log")
    run_prefix = gate.get("run_id", "")[:8] if gate else ""
    market_offers = [o for o in offers if o.get("run_id", "").startswith(run_prefix)] if run_prefix else []

    return {
        "name": gate.get("micro_market", business_id) if gate else business_id,
        "payer": gate.get("payer", "") if gate else "",
        "offers": market_offers[:3],
    }


def _try_supabase_upsert(post_data: dict) -> bool:
    """Try to upsert to Supabase. Returns True on success."""
    try:
        from utils.supabase_client import upsert_post
        return upsert_post(post_data)
    except Exception as e:
        logger.warning(f"Supabase upsert failed (will use Sheets fallback): {e}")
        return False


def generate_articles(business_id: str, media_id: str = DEFAULT_MEDIA_ID) -> int:
    """Generate all blog articles for a business.

    Full flow:
    1. Register business in Supabase (auto-generates slug)
    2. Generate market-specific topics via AI
    3. Generate 50 articles (10 categories x 5)
    4. Auto-assign cover images from Supabase Storage pool
    5. Send Slack notification with blog URL

    Returns the number of articles generated.
    """
    # Step 1: Ensure business is registered
    try:
        from utils.supabase_client import ensure_business
        biz = ensure_business(business_id)
        if biz:
            logger.info(f"Business ready: {biz.get('slug')} ({biz.get('display_name')})")
        else:
            logger.warning(f"Could not register business '{business_id}' — blog will still generate")
    except Exception as e:
        logger.warning(f"Business registration skipped: {e}")

    market = _get_market_info(business_id)
    lp_url = f"{LP_BASE_URL}/lp/{quote(business_id, safe='')}"

    # Step 2: Generate market-specific topics
    topics_map = _generate_topics(
        market_name=market["name"],
        payer=market.get("payer", ""),
        offers=market.get("offers", []),
    )

    template = jinja_env.get_template("blog_prompt.j2")

    # Check existing articles (try Supabase first, fall back to Sheets)
    existing_slugs: set[str] = set()
    try:
        from utils.supabase_client import get_existing_slugs
        existing_slugs = get_existing_slugs(media_id)
        logger.info(f"Loaded {len(existing_slugs)} existing slugs from Supabase")
    except Exception:
        existing = get_all_rows("blog_articles")
        existing_slugs = {r.get("slug", "") for r in existing}
        logger.info(f"Loaded {len(existing_slugs)} existing slugs from Sheets")

    # Step 3: Generate articles
    total_generated = 0
    now_base = datetime.now()
    article_index = 0
    # Spread published_at over the past 30 days (not future) so articles are immediately visible
    total_articles = 50

    for cat_key in CATEGORY_KEYS:
        cat_info = topics_map.get(cat_key, {})
        if not cat_info:
            continue
        for topic in cat_info.get("topics", []):
            article_index += 1
            logger.info(f"[{article_index}/50] Generating: {topic[:40]}...")

            prompt = template.render(
                name=market["name"],
                target_audience=market.get("payer", "経営者・意思決定者"),
                lp_url=lp_url,
                category=cat_info["label"],
                topic=topic,
            )

            try:
                result = generate_json_with_retry(
                    prompt=prompt,
                    system="あなたはBtoB SEOコンテンツライターです。指定のJSONオブジェクトで正確に出力してください。",
                    max_tokens=8192,
                    temperature=0.75,
                    max_retries=3,
                )

                if isinstance(result, list):
                    result = result[0] if result else {}

                slug = result.get("slug", "")
                if not slug or slug in existing_slugs:
                    slug = f"article-{uuid.uuid4().hex[:8]}"

                # Spread published_at over the past 30 days so articles are immediately visible
                # Article 1 = 30 days ago, Article 50 = now (oldest first for natural SEO)
                days_back = 30 * (1 - article_index / max(total_articles, 1))
                published_at = (now_base - timedelta(days=days_back)).isoformat()
                generated_at = now_base.isoformat()

                tags = result.get("tags", [])
                if not isinstance(tags, list):
                    tags = [str(tags)] if tags else []

                body_html = result.get("body_html", "")

                # --- Supabase (primary) ---
                post_data = {
                    "business_id": business_id,
                    "media_id": media_id,
                    "title": result.get("title", topic),
                    "slug": slug,
                    "body_html": body_html,
                    "excerpt": result.get("excerpt", ""),
                    "category": cat_info["label"],
                    "tags": tags,
                    "meta_description": result.get("meta_description", ""),
                    "og_title": result.get("og_title", result.get("title", topic)),
                    "og_description": result.get("og_description", ""),
                    "status": "published",
                    "published_at": published_at,
                    "generated_at": generated_at,
                }

                supabase_ok = _try_supabase_upsert(post_data)

                # --- Sheets fallback ---
                if not supabase_ok:
                    article_id = f"art_{uuid.uuid4().hex[:12]}"
                    tags_str = json.dumps(tags, ensure_ascii=False)
                    row = [
                        article_id, business_id,
                        result.get("title", topic), slug, body_html,
                        result.get("excerpt", ""), cat_info["label"], tags_str,
                        result.get("meta_description", ""),
                        result.get("og_title", result.get("title", topic)),
                        result.get("og_description", ""),
                        "published", published_at, generated_at,
                    ]
                    append_rows("blog_articles", [row])

                # --- GCS backup ---
                try:
                    gcs_upload(f"blog_articles/{slug}.json", post_data)
                except Exception as e:
                    logger.warning(f"GCS upload failed for {slug}: {e}")

                existing_slugs.add(slug)
                total_generated += 1
                logger.info(f"  → Generated: {result.get('title', topic)[:40]} ({'supabase' if supabase_ok else 'sheets'})")

            except Exception as e:
                logger.error(f"Failed to generate article '{topic[:30]}': {e}")
                continue

    # Step 4: Auto-assign cover images
    if total_generated > 0:
        img_count = _assign_cover_images(business_id, media_id)
        logger.info(f"Cover images assigned: {img_count}")

    # Step 5: Slack notification
    if total_generated > 0:
        blog_url = LP_BASE_URL
        try:
            from utils.supabase_client import get_client
            res = get_client().table("businesses").select("slug").eq("business_id", business_id).single().execute()
            if res.data:
                blog_url = f"{LP_BASE_URL}/{res.data['slug']}"
        except Exception:
            pass
        slack_notify(
            f":page_facing_up: ブログ記事を *{total_generated}件* 自動生成しました\n"
            f"事業: {business_id[:30]}\n"
            f"ブログ: {blog_url}"
        )

    return total_generated


def generate_seo_articles(
    business_id: str,
    run_id: str,
    seo_keywords: dict | None = None,
    market_name: str = "",
    media_id: str = DEFAULT_MEDIA_ID,
    max_articles: int = 8,
) -> int:
    """Generate SEO-targeted articles based on keyword research data.

    Uses content_calendar from seo_keywords module to create
    targeted blog articles for each planned keyword.

    Args:
        business_id: Target business identifier.
        run_id: Pipeline run ID for traceability.
        seo_keywords: Output from research_keywords() containing
            primary_keywords, longtail_keywords, content_calendar.
        market_name: Market name for context.
        media_id: Blog media identifier.
        max_articles: Max articles to generate per batch.

    Returns:
        Number of articles generated.
    """
    if not seo_keywords:
        try:
            from utils.seo_keywords import research_keywords
            seo_keywords = research_keywords(
                market_name=market_name or business_id,
                run_id=run_id,
                industry=market_name,
            )
        except Exception as e:
            logger.error(f"Failed to get SEO keywords: {e}")
            return 0

    calendar = seo_keywords.get("content_calendar", [])
    primary_kws = seo_keywords.get("primary_keywords", [])
    longtail_kws = seo_keywords.get("longtail_keywords", [])

    if not calendar:
        logger.warning("No content calendar in SEO keywords data.")
        return 0

    # Build keyword context for better articles
    kw_context = "主要キーワード:\n"
    for kw in primary_kws[:5]:
        kw_context += f"- {kw.get('keyword', '')} ({kw.get('intent', '')})\n"
    kw_context += "\nロングテール:\n"
    for kw in longtail_kws[:10]:
        kw_context += f"- {kw.get('keyword', '')} [{kw.get('topic_cluster', '')}]\n"

    # Check existing slugs
    existing_slugs: set[str] = set()
    try:
        from utils.supabase_client import get_existing_slugs
        existing_slugs = get_existing_slugs(media_id)
    except Exception:
        existing = get_all_rows("blog_articles")
        existing_slugs = {r.get("slug", "") for r in existing}

    lp_url = f"{LP_BASE_URL}/lp/{quote(business_id, safe='')}"
    template = jinja_env.get_template("blog_prompt.j2")
    now_base = datetime.now()
    total = 0

    for i, entry in enumerate(calendar[:max_articles]):
        keyword = entry.get("keyword", "")
        content_type = entry.get("content_type", "記事")
        title_idea = entry.get("title_idea", keyword)

        if not keyword:
            continue

        logger.info(f"[SEO {i+1}/{min(len(calendar), max_articles)}] {title_idea[:40]}...")

        prompt = (
            f"以下のSEOキーワードに最適化されたブログ記事をJSON形式で生成してください。\n\n"
            f"ターゲットキーワード: {keyword}\n"
            f"記事タイプ: {content_type}\n"
            f"タイトル案: {title_idea}\n"
            f"市場: {market_name or business_id}\n"
            f"LP URL: {lp_url}\n\n"
            f"{kw_context}\n\n"
            f'出力形式:\n'
            f'{{"title": "SEO最適化タイトル（キーワード含む）",\n'
            f' "slug": "url-safe-slug",\n'
            f' "body_html": "<h2>見出し</h2><p>本文...</p>（2000文字以上）",\n'
            f' "excerpt": "記事の要約（120文字以内）",\n'
            f' "tags": ["タグ1", "タグ2"],\n'
            f' "meta_description": "SEOメタディスクリプション（120文字以内）",\n'
            f' "og_title": "OGPタイトル",\n'
            f' "og_description": "OGP説明文"}}\n\n'
            f"制約:\n"
            f"- タイトルとH2にターゲットキーワードを自然に含める\n"
            f"- 業務代行型サービスの訴求を本文に含める\n"
            f"- LP URLへの誘導CTAを記事末尾に入れる\n"
            f"- ロングテールキーワードも本文中に散りばめる"
        )

        try:
            result = generate_json_with_retry(
                prompt=prompt,
                system=(
                    "あなたはBtoB SEOコンテンツライターです。"
                    "ターゲットキーワードで上位表示を狙える記事を生成してください。"
                    "指定のJSONオブジェクトで正確に出力してください。"
                ),
                max_tokens=8192,
                temperature=0.7,
                max_retries=3,
            )

            if isinstance(result, list):
                result = result[0] if result else {}

            slug = result.get("slug", "")
            if not slug or slug in existing_slugs:
                slug = f"seo-{uuid.uuid4().hex[:8]}"

            days_back = max(max_articles - total, 1)
            published_at = (now_base - timedelta(days=days_back)).isoformat()

            tags = result.get("tags", [])
            if not isinstance(tags, list):
                tags = [str(tags)] if tags else []

            post_data = {
                "business_id": business_id,
                "media_id": media_id,
                "title": result.get("title", title_idea),
                "slug": slug,
                "body_html": result.get("body_html", ""),
                "excerpt": result.get("excerpt", ""),
                "category": content_type,
                "tags": tags,
                "meta_description": result.get("meta_description", ""),
                "og_title": result.get("og_title", result.get("title", title_idea)),
                "og_description": result.get("og_description", ""),
                "status": "published",
                "published_at": published_at,
                "generated_at": now_base.isoformat(),
            }

            supabase_ok = _try_supabase_upsert(post_data)

            if not supabase_ok:
                article_id = f"seo_{uuid.uuid4().hex[:12]}"
                tags_str = json.dumps(tags, ensure_ascii=False)
                row = [
                    article_id, business_id,
                    result.get("title", title_idea), slug,
                    result.get("body_html", ""),
                    result.get("excerpt", ""), content_type, tags_str,
                    result.get("meta_description", ""),
                    result.get("og_title", ""),
                    result.get("og_description", ""),
                    "published", published_at, now_base.isoformat(),
                ]
                append_rows("blog_articles", [row])

            try:
                gcs_upload(f"blog_articles/{slug}.json", post_data)
            except Exception:
                pass

            existing_slugs.add(slug)
            total += 1
            logger.info(f"  → SEO article: {result.get('title', '')[:40]} [KW: {keyword}]")

        except Exception as e:
            logger.error(f"Failed to generate SEO article for '{keyword}': {e}")
            continue

    logger.info(f"SEO batch complete: {total} articles for {market_name or business_id}")
    return total


def _get_all_business_ids() -> list[str]:
    """Get all unique business_ids from lp_content sheet that need blog articles."""
    lp_rows = get_all_rows("lp_content")
    blog_rows = get_all_rows("blog_articles")

    # All business IDs that have LPs
    lp_biz_ids = {r.get("business_id", "") for r in lp_rows if r.get("business_id")}

    # Business IDs that already have blog articles
    blog_biz_ids = {r.get("business_id", "") for r in blog_rows if r.get("business_id")}

    # Return business IDs that have LPs but no blog articles yet
    needs_blog = lp_biz_ids - blog_biz_ids
    if not needs_blog:
        logger.info(f"All {len(lp_biz_ids)} businesses already have blog articles")
        # Fall back to all LP businesses (may generate additional articles)
        return sorted(lp_biz_ids)

    logger.info(f"Found {len(needs_blog)} businesses needing blog articles (of {len(lp_biz_ids)} total)")
    return sorted(needs_blog)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate blog articles")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--business-id", help="Target business ID (market name)")
    group.add_argument("--all", action="store_true", help="Generate for ALL businesses with LPs")
    parser.add_argument("--media-id", default=DEFAULT_MEDIA_ID, help="Media ID (default: shokunin-san)")
    parser.add_argument("--seo-mode", action="store_true", help="Use SEO keyword-driven generation")
    parser.add_argument("--run-id", default="", help="Pipeline run ID (for SEO mode)")
    parser.add_argument("--max-articles", type=int, default=8, help="Max articles for SEO batch")
    args = parser.parse_args()

    # Determine target business IDs
    if args.all:
        business_ids = _get_all_business_ids()
        if not business_ids:
            logger.info("No businesses found in lp_content. Nothing to generate.")
            slack_notify(":page_facing_up: ブログ生成: 対象事業案なし")
            return
        logger.info(f"=== Blog generator start: --all mode, {len(business_ids)} businesses ===")
    else:
        business_ids = [args.business_id]
        logger.info(f"=== Blog generator start: {args.business_id} (media: {args.media_id}) ===")

    grand_total = 0
    for i, biz_id in enumerate(business_ids, 1):
        logger.info(f"--- Business [{i}/{len(business_ids)}]: {biz_id[:40]} ---")
        try:
            if args.seo_mode:
                total = generate_seo_articles(
                    business_id=biz_id,
                    run_id=args.run_id or f"manual_{uuid.uuid4().hex[:8]}",
                    market_name=biz_id,
                    media_id=args.media_id,
                    max_articles=args.max_articles,
                )
            else:
                total = generate_articles(business_id=biz_id, media_id=args.media_id)
            grand_total += total
            logger.info(f"  → {total} articles generated for {biz_id[:30]}")
        except Exception as e:
            logger.error(f"Failed to generate for {biz_id[:30]}: {e}", exc_info=True)
            continue

    logger.info(f"=== Blog generator complete: {grand_total} articles across {len(business_ids)} businesses ===")

    # Summary notification for --all mode
    if args.all and grand_total > 0:
        slack_notify(
            f":page_facing_up: ブログ記事を *{grand_total}件* 自動生成しました\n"
            f"対象事業: {len(business_ids)}件"
        )
    # SEO mode notification (generate_articles already has built-in Slack notification)
    elif not args.all and grand_total > 0 and args.seo_mode:
        blog_url = LP_BASE_URL
        try:
            from utils.supabase_client import get_client
            res = get_client().table("businesses").select("slug").eq("business_id", args.business_id).single().execute()
            if res.data:
                blog_url = f"{LP_BASE_URL}/{res.data['slug']}"
        except Exception:
            pass
        slack_notify(
            f":page_facing_up: SEOブログ記事を *{grand_total}件* 生成しました\n"
            f"事業: {args.business_id[:30]}\n"
            f"ブログ: {blog_url}"
        )


if __name__ == "__main__":
    main()
