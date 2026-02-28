"""
blog_generator.py — Generate 50 SEO blog articles for a target market.

Generates articles across 10 categories (5 per category),
stores in Supabase posts table (primary) and blog_articles sheet (fallback).
"""

import sys
import uuid
import json
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

LP_BASE_URL = "https://lp-app-pi.vercel.app"
DEFAULT_MEDIA_ID = "shokunin-san"

# 10 categories x 5 articles each = 50 articles
ARTICLE_TOPICS = {
    "industry_challenges": {
        "label": "業界課題解説",
        "topics": [
            "住宅塗装業界が抱える見積もり作成の3大課題と解決策",
            "塗装リフォーム会社の利益率を圧迫する「見えないコスト」とは",
            "なぜ塗装見積もりのミスが受注率低下につながるのか",
            "住宅塗装業の人手不足と見積もり業務の関係性",
            "お客様が塗装会社を比較するとき、見積もりの何を見ているか",
        ],
    },
    "howto": {
        "label": "ハウツー",
        "topics": [
            "住宅塗装の見積もり精度を上げる5つの実践テクニック",
            "初回訪問で顧客の信頼を掴む見積もりプレゼン術",
            "塗装見積もりで「高い」と言われたときの対処法",
            "リフォーム見積もり作成時間を半分にする方法",
            "塗装面積の計測ミスを防ぐためのチェックポイント",
        ],
    },
    "comparison": {
        "label": "比較記事",
        "topics": [
            "手書き vs Excel vs AI：塗装見積もりツール徹底比較",
            "見積もりソフト導入前後で何が変わる？現場の声を分析",
            "大手塗装会社 vs 地域密着型：見積もり戦略の違い",
            "塗装見積もりの「値引き交渉」を減らすための価格提示法",
            "顧客満足度が高い見積もり書の特徴とは",
        ],
    },
    "case_study": {
        "label": "事例紹介",
        "topics": [
            "見積もり自動化で月20時間の工数削減を実現した塗装会社の事例",
            "受注率30%アップを達成した塗装リフォーム会社の取り組み",
            "3人の会社がAI見積もりで大手と競争できるようになった話",
            "顧客の要望をそのまま見積もりに反映する仕組みづくり",
            "見積もり提出スピードを上げて成約率を改善した方法",
        ],
    },
    "trend": {
        "label": "トレンド",
        "topics": [
            "2026年の住宅塗装業界で起きているDX化の波",
            "AIが変える塗装リフォームの未来：自動見積もりから施工管理まで",
            "住宅リフォーム市場の成長と塗装業者に求められる変化",
            "デジタル化が進む住宅メンテナンス市場の最新動向",
            "お客様が求める「見える化」と塗装業界の対応",
        ],
    },
    "qa": {
        "label": "Q&A",
        "topics": [
            "住宅塗装の見積もりに関するよくある質問10選",
            "塗装見積もりソフトの導入でよく聞かれる疑問に回答",
            "お客様から「なぜこの金額？」と聞かれたときの説明術",
            "塗装見積もりの「坪単価」と「平米単価」どちらが正しい？",
            "外壁塗装の見積もり項目：何を含めるべき？完全ガイド",
        ],
    },
    "checklist": {
        "label": "チェックリスト",
        "topics": [
            "住宅塗装見積もり作成前の現場調査チェックリスト",
            "見積もり書に入れるべき項目チェックリスト【完全版】",
            "塗装リフォーム営業の初回訪問チェックリスト",
            "見積もり提出前の最終確認チェックリスト",
            "塗装会社のIT化チェックリスト：最初にやるべき5つ",
        ],
    },
    "glossary": {
        "label": "用語解説",
        "topics": [
            "住宅塗装の見積もりで使われる専門用語を解説",
            "外壁塗装の塗料グレードと価格帯の基礎知識",
            "リフォーム見積もりの「諸経費」とは何か：内訳を解説",
            "塗装面積の計算方法：壁面積・屋根面積の求め方",
            "塗装見積もりの「下地処理」項目を正しく理解する",
        ],
    },
    "management": {
        "label": "経営者向け",
        "topics": [
            "塗装会社の利益率を改善する見積もり戦略",
            "小規模塗装会社がIT投資で得られる3つのメリット",
            "塗装業の経営者が知っておくべきDX補助金制度",
            "見積もり業務の属人化リスクと解消方法",
            "塗装会社の成長を加速させるデータ活用のすすめ",
        ],
    },
    "seo_longtail": {
        "label": "SEOロングテール",
        "topics": [
            "外壁塗装の見積もりが遅い？スピード改善の方法",
            "塗装リフォームの見積もり比較：失敗しない選び方",
            "住宅塗装の見積もり金額の相場と適正価格の見極め方",
            "塗装見積もりを早く正確に作るコツ【現場プロ直伝】",
            "リフォーム見積もりをデジタル化するメリットと注意点",
        ],
    },
}


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
    """Generate all blog articles for a business."""
    # Ensure business is registered in businesses table (auto-generates slug)
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

    total_generated = 0
    now_base = datetime.now()
    article_index = 0

    for cat_key, cat_info in ARTICLE_TOPICS.items():
        for topic in cat_info["topics"]:
            article_index += 1
            logger.info(f"[{article_index}/50] Generating: {topic[:40]}...")

            prompt = template.render(
                name=market["name"],
                target_audience=market.get("payer", "塗装業の経営者"),
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

                # Stagger published_at (1 per hour for SEO drip)
                published_at = (now_base + timedelta(hours=article_index)).isoformat()
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

            published_at = (now_base + timedelta(hours=total + 1)).isoformat()

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


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate blog articles")
    parser.add_argument("--business-id", required=True, help="Target business ID (market name)")
    parser.add_argument("--media-id", default=DEFAULT_MEDIA_ID, help="Media ID (default: shokunin-san)")
    parser.add_argument("--seo-mode", action="store_true", help="Use SEO keyword-driven generation")
    parser.add_argument("--run-id", default="", help="Pipeline run ID (for SEO mode)")
    parser.add_argument("--max-articles", type=int, default=8, help="Max articles for SEO batch")
    args = parser.parse_args()

    logger.info(f"=== Blog generator start: {args.business_id} (media: {args.media_id}) ===")

    if args.seo_mode:
        total = generate_seo_articles(
            business_id=args.business_id,
            run_id=args.run_id or f"manual_{uuid.uuid4().hex[:8]}",
            market_name=args.business_id,
            media_id=args.media_id,
            max_articles=args.max_articles,
        )
    else:
        total = generate_articles(business_id=args.business_id, media_id=args.media_id)

    logger.info(f"=== Blog generator complete: {total} articles generated ===")
    if total > 0:
        blog_url = f"{LP_BASE_URL}"
        try:
            from utils.supabase_client import get_client
            res = get_client().table("businesses").select("slug").eq("business_id", args.business_id).single().execute()
            if res.data:
                blog_url = f"{LP_BASE_URL}/{res.data['slug']}"
        except Exception:
            pass
        mode_str = "SEO" if args.seo_mode else "標準"
        slack_notify(
            f":page_facing_up: ブログ記事を *{total}件* 生成しました ({mode_str})\n"
            f"事業: {args.business_id[:30]}\n"
            f"ブログ: {blog_url}"
        )


if __name__ == "__main__":
    main()
