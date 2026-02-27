"""
sns_batch_generator.py — Generate 100 SNS posts in batch for a target market.

Generates varied posts across 10 categories, stores in sns_queue sheet.
Run once per market to pre-generate all posts, then sns_scheduled_poster.py
handles actual posting.
"""

import sys
import uuid
from pathlib import Path
from datetime import datetime
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import TEMPLATES_DIR, get_logger
from utils.claude_client import generate_json_with_retry
from utils.sheets_client import get_all_rows, append_rows
from utils.slack_notifier import send_message as slack_notify

logger = get_logger("sns_batch_generator", "sns_batch_generator.log")

jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

LP_BASE_URL = "https://lp-app-pi.vercel.app"

# 10 categories x 10 posts each = 100 posts
CATEGORIES = {
    "problem_awareness": {
        "label": "課題提起型",
        "instruction": "ターゲットが日常で感じている見積もり作成の悩み・課題を生々しく描写。共感を生む投稿。"
    },
    "solution": {
        "label": "解決提示型",
        "instruction": "AIによる自動見積もりがどう課題を解決するかを端的に伝える。導入メリットを強調。"
    },
    "stats": {
        "label": "数字・統計型",
        "instruction": "塗装業界の統計や数字（見積もり作成にかかる平均時間、人件費、受注率など）を使って説得力のある投稿。数字は現実的な範囲で。"
    },
    "question": {
        "label": "質問型",
        "instruction": "ターゲットに問いかける形式の投稿。「あなたは大丈夫？」「知っていましたか？」など、つい反応したくなる質問。"
    },
    "before_after": {
        "label": "ビフォーアフター型",
        "instruction": "導入前と導入後の変化を対比で見せる。時間短縮、正確性向上、受注率アップなどの具体的変化。"
    },
    "voice": {
        "label": "利用者の声型",
        "instruction": "想定利用者の声として「導入してよかった」系の投稿。ただし実在しない人物の名前は使わず、業種・役職で表現。"
    },
    "industry_news": {
        "label": "業界ニュース型",
        "instruction": "塗装・リフォーム業界のDX化トレンド、人手不足問題、働き方改革などのニュースに絡めた投稿。"
    },
    "tips": {
        "label": "Tips・ノウハウ型",
        "instruction": "塗装見積もりのコツ、お客様対応のポイント、受注率を上げる秘訣など、実務に役立つ情報。"
    },
    "limited": {
        "label": "限定・特典型",
        "instruction": "無料トライアル、初月無料、限定相談会などのオファーを訴求。ただし誇大表現は避ける。"
    },
    "lp_direct": {
        "label": "LP誘導型",
        "instruction": "「詳しくはこちら」「3分でわかる」など、LPへの直接誘導を目的とした投稿。CTAを明確に。"
    },
}


def _get_market_info(business_id: str) -> dict:
    """Get market details for the target business."""
    gates = get_all_rows("gate_decision_log")
    gate = None
    for g in gates:
        if g.get("run_id", "").startswith(business_id[:8]) and g.get("status") == "PASS":
            if g.get("micro_market", "") == business_id or not gate:
                gate = g

    offers = get_all_rows("offer_3_log")
    market_offers = [o for o in offers if o.get("run_id", "").startswith(business_id[:8] if len(business_id) > 8 else business_id)]

    lp_content = get_all_rows("lp_content")
    lp = next((l for l in lp_content if l.get("business_id", "") == business_id), None)

    return {
        "name": gate.get("micro_market", business_id) if gate else business_id,
        "payer": gate.get("payer", "") if gate else "",
        "offers": market_offers[:3],
        "headline": lp.get("headline", "") if lp else "",
    }


def generate_batch(
    business_id: str,
    platform: str = "twitter",
    posts_per_category: int = 10,
) -> int:
    """Generate batch posts for a single platform and store in sns_queue."""
    market = _get_market_info(business_id)
    lp_url = f"{LP_BASE_URL}/lp/{quote(business_id, safe='')}"

    # Format offers
    offers_text = ""
    for i, o in enumerate(market.get("offers", []), 1):
        offers_text += f"  {i}. {o.get('offer_name', '')} — {o.get('price', '')}\n"

    template = jinja_env.get_template("sns_batch_prompt.j2")
    total_generated = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    for cat_key, cat_info in CATEGORIES.items():
        logger.info(f"Generating {posts_per_category} {platform} posts: {cat_info['label']}")

        prompt = template.render(
            platform=platform,
            name=market["name"],
            target_audience=market.get("payer", "塗装業の経営者"),
            lp_url=lp_url,
            offers_text=offers_text,
            category=cat_info["label"],
            category_instruction=cat_info["instruction"],
            num_posts=posts_per_category,
        )

        try:
            posts = generate_json_with_retry(
                prompt=prompt,
                system="あなたは日本のBtoB SNSマーケティングの専門家です。指定のJSON配列で正確に出力してください。",
                max_tokens=8192,
                temperature=0.85,
                max_retries=3,
            )

            if isinstance(posts, dict):
                posts = posts.get("posts", [posts])
            if not isinstance(posts, list):
                posts = [posts]

            rows = []
            for p in posts:
                if not isinstance(p, dict) or "text" not in p:
                    continue
                queue_id = f"sq_{uuid.uuid4().hex[:12]}"
                rows.append([
                    queue_id,
                    business_id,
                    platform,
                    p["text"],
                    cat_key,
                    "queued",
                    "",       # scheduled_at
                    "",       # posted_at
                    "",       # post_url
                    "",       # error_detail
                ])

            if rows:
                append_rows("sns_queue", rows)
                total_generated += len(rows)
                logger.info(f"  → {len(rows)} posts queued for {cat_info['label']}")

        except Exception as e:
            logger.error(f"Failed to generate {cat_info['label']}: {e}")
            continue

    return total_generated


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate batch SNS posts")
    parser.add_argument("--business-id", required=True, help="Target business ID (market name)")
    parser.add_argument("--platform", default="twitter", choices=["twitter", "linkedin"])
    parser.add_argument("--per-category", type=int, default=10)
    args = parser.parse_args()

    logger.info(f"=== SNS batch generator start: {args.business_id} ({args.platform}) ===")

    total = generate_batch(
        business_id=args.business_id,
        platform=args.platform,
        posts_per_category=args.per_category,
    )

    logger.info(f"=== SNS batch generator complete: {total} posts queued ===")
    if total > 0:
        slack_notify(
            f":mega: SNS投稿を *{total}件* バッチ生成しました\n"
            f"プラットフォーム: {args.platform}\n"
            f"事業: {args.business_id[:30]}\n"
            f"スケジュール投稿で順次配信されます。"
        )


if __name__ == "__main__":
    main()
