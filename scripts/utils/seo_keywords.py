"""
seo_keywords.py — Module K: SEO keyword research and strategy.

Generates keyword clusters for blog SEO content strategy:
  - Primary keywords (high intent, business-related)
  - Long-tail keywords (specific problems/solutions)
  - Content calendar mapping
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_logger
from utils.claude_client import generate_json_with_retry
from utils.sheets_client import append_rows

logger = get_logger("seo_keywords", "seo_keywords.log")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def _get_google_suggestions(seed: str) -> list[str]:
    """Get Google autocomplete suggestions for a seed keyword."""
    suggestions = []
    try:
        resp = requests.get(
            "https://suggestqueries.google.com/complete/search",
            params={"q": seed, "client": "firefox", "hl": "ja"},
            headers=HEADERS,
            timeout=10,
        )
        data = resp.json()
        if isinstance(data, list) and len(data) >= 2:
            suggestions = [s for s in data[1] if isinstance(s, str)]
    except Exception as e:
        logger.warning(f"Google suggestions failed for '{seed}': {e}")
    return suggestions[:10]


def _get_related_searches(keyword: str) -> list[str]:
    """Get related searches from Google SERP."""
    related = []
    try:
        resp = requests.get(
            "https://www.google.com/search",
            params={"q": keyword, "hl": "ja", "gl": "jp"},
            headers=HEADERS,
            timeout=15,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        for el in soup.select("div.s75CSd a"):
            text = el.get_text(strip=True)
            if text:
                related.append(text)
    except Exception as e:
        logger.warning(f"Related searches failed: {e}")
    return related[:10]


def research_keywords(
    market_name: str,
    run_id: str,
    industry: str = "",
    seed_count: int = 5,
) -> dict:
    """Research SEO keywords for a market.

    Returns {
        primary_keywords: list[{keyword, intent, search_type}],
        longtail_keywords: list[{keyword, topic_cluster}],
        content_calendar: list[{week, keyword, content_type, title_idea}],
        total_keywords: int,
    }
    """
    # Generate seed keywords from market/industry
    seeds = [
        f"{industry} 代行",
        f"{industry} 外注",
        f"{industry} 業務効率化",
        f"{market_name}",
        f"{industry} AI 自動化",
    ][:seed_count]

    # Collect suggestions and related searches
    all_suggestions = []
    all_related = []

    for seed in seeds:
        suggestions = _get_google_suggestions(seed)
        all_suggestions.extend(suggestions)
        time.sleep(1.0)

        related = _get_related_searches(seed)
        all_related.extend(related)
        time.sleep(2.0)

    # Deduplicate
    all_keywords = list(dict.fromkeys(all_suggestions + all_related))

    # Use AI to cluster and categorize
    prompt = (
        f"以下のキーワードリストを分析し、SEOコンテンツ戦略を策定してください。\n\n"
        f"市場: {market_name}\n"
        f"業種: {industry}\n"
        f"収集キーワード ({len(all_keywords)}件):\n"
        f"{json.dumps(all_keywords[:50], ensure_ascii=False)}\n\n"
        f"以下のJSON形式で出力:\n"
        f'{{"primary_keywords": [{{"keyword": "KW", "intent": "transactional/informational", '
        f'"search_type": "業務代行/比較/How-to"}}],\n'
        f'  "longtail_keywords": [{{"keyword": "ロングテールKW", "topic_cluster": "クラスタ名"}}],\n'
        f'  "content_calendar": [{{"week": 1, "keyword": "KW", '
        f'"content_type": "記事/比較/事例", "title_idea": "タイトル案"}}]}}\n\n'
        f"制約:\n"
        f"- primary_keywords: 10件以内（高意図KWのみ）\n"
        f"- longtail_keywords: 20件以内\n"
        f"- content_calendar: 4週間分（週2記事）\n"
        f"- 業務代行型ビジネスに関連するKWを優先"
    )

    result = generate_json_with_retry(
        prompt=prompt,
        system=(
            "あなたはBtoB SEOの専門家です。"
            "業務代行型ビジネスのコンテンツマーケティング戦略を策定してください。"
        ),
        max_tokens=8192,
        temperature=0.4,
        max_retries=2,
    )

    if isinstance(result, list):
        result = result[0] if result else {}

    result["total_keywords"] = len(all_keywords)

    # Save to sheets
    try:
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        append_rows("seo_keywords_log", [[
            run_id,
            market_name,
            industry,
            json.dumps(result.get("primary_keywords", []), ensure_ascii=False),
            json.dumps(result.get("longtail_keywords", []), ensure_ascii=False),
            json.dumps(result.get("content_calendar", []), ensure_ascii=False),
            len(all_keywords),
            now,
        ]])
    except Exception as e:
        logger.warning(f"Failed to save SEO keywords: {e}")

    logger.info(
        f"SEO keywords for {market_name}: "
        f"{len(result.get('primary_keywords', []))} primary, "
        f"{len(result.get('longtail_keywords', []))} longtail"
    )

    return result
