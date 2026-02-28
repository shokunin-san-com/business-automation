"""
search_volume.py — Google search demand verification (replaces A1q/A1d).

Uses Google search to verify real demand signals for micro-markets:
  1. Keyword search volume indicators (result count, ad presence)
  2. Related keyword expansion
  3. Competitor ad activity check

Returns PASS/FAIL with evidence URLs. No scoring.

Schedule: triggered by orchestrate_v2.py after A0
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from datetime import datetime

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_logger
from utils.sheets_client import get_all_rows, append_rows, ensure_sheet_exists
from utils.claude_client import generate_json_with_retry

logger = get_logger("search_volume", "search_volume.log")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# Sheet setup
SV_SHEET = "search_volume_log"
SV_HEADERS = [
    "run_id", "micro_market", "keyword", "result_count",
    "has_ads", "related_keywords", "evidence_urls",
    "status", "checked_at",
]

# Thresholds for PASS
MIN_RESULT_COUNT = 10000  # Google results
MIN_KEYWORDS_WITH_ADS = 1  # At least 1 keyword shows ads


def _google_search_indicators(keyword: str) -> dict:
    """Search Google and extract demand indicators.

    Returns {result_count, has_ads, top_urls, related_searches}.
    """
    indicators = {
        "result_count": 0,
        "has_ads": False,
        "top_urls": [],
        "related_searches": [],
    }

    try:
        params = {"q": keyword, "num": 10, "hl": "ja", "gl": "jp"}
        resp = requests.get(
            "https://www.google.com/search",
            params=params,
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Extract result count from "約 X,XXX,XXX 件"
        stats = soup.find("div", id="result-stats")
        if stats:
            text = stats.get_text()
            nums = re.findall(r"[\d,]+", text)
            if nums:
                indicators["result_count"] = int(nums[0].replace(",", ""))

        # Check for ads (sponsored results)
        ad_markers = soup.select("[data-text-ad]") or soup.select("div.uEierd")
        if not ad_markers:
            # Alternative ad detection
            for span in soup.find_all("span"):
                if span.get_text(strip=True) in ("スポンサー", "広告", "Ad"):
                    ad_markers = [span]
                    break
        indicators["has_ads"] = len(ad_markers) > 0

        # Top organic URLs
        for g in soup.select("div.g")[:5]:
            link = g.select_one("a[href]")
            if link:
                href = link.get("href", "")
                if href.startswith("http"):
                    indicators["top_urls"].append(href)

        # Related searches
        for rel in soup.select("div.s75CSd a"):
            text = rel.get_text(strip=True)
            if text:
                indicators["related_searches"].append(text)

    except Exception as e:
        logger.warning(f"Google search failed for '{keyword}': {e}")

    return indicators


def verify_market_demand(
    micro_market: dict,
    run_id: str,
    search_delay: float = 3.0,
) -> dict:
    """Verify demand for a single micro-market using search indicators.

    Generates 3 search keywords from the market data, checks each,
    and makes a PASS/FAIL decision based on aggregate signals.

    Returns {status, keywords_checked, evidence_urls, result_summary}.
    """
    market_name = micro_market.get("micro_market", "")
    industry = micro_market.get("industry", "")
    task = micro_market.get("task", "")
    intent_word = micro_market.get("intent_word", "")

    # Generate search keywords
    keywords = [
        f"{industry} {task} 代行",
        f"{industry} {task} 外注",
        f"{market_name}",
    ]
    if intent_word:
        keywords.append(f"{industry} {intent_word}")

    total_results = 0
    ads_found = 0
    all_evidence_urls = []
    all_related = []
    keyword_results = []

    for kw in keywords[:4]:
        indicators = _google_search_indicators(kw)
        total_results += indicators["result_count"]
        if indicators["has_ads"]:
            ads_found += 1
        all_evidence_urls.extend(indicators["top_urls"][:3])
        all_related.extend(indicators["related_searches"][:3])

        keyword_results.append({
            "keyword": kw,
            "result_count": indicators["result_count"],
            "has_ads": indicators["has_ads"],
        })

        time.sleep(search_delay)

    # Decision: PASS if sufficient demand signals
    avg_results = total_results / max(len(keywords[:4]), 1)
    status = "PASS" if (avg_results >= MIN_RESULT_COUNT or ads_found >= MIN_KEYWORDS_WITH_ADS) else "FAIL"

    fail_reasons = []
    if avg_results < MIN_RESULT_COUNT:
        fail_reasons.append(f"検索結果平均{int(avg_results)}件 < {MIN_RESULT_COUNT}")
    if ads_found < MIN_KEYWORDS_WITH_ADS:
        fail_reasons.append(f"広告表示{ads_found}KW < {MIN_KEYWORDS_WITH_ADS}")

    # Deduplicate URLs
    evidence_urls = list(dict.fromkeys(all_evidence_urls))[:10]
    related_kws = list(dict.fromkeys(all_related))[:10]

    result = {
        "micro_market": market_name,
        "status": status,
        "fail_reasons": fail_reasons,
        "keywords_checked": keyword_results,
        "avg_result_count": int(avg_results),
        "ads_found": ads_found,
        "evidence_urls": evidence_urls,
        "related_keywords": related_kws,
    }

    # Save to sheet
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for kr in keyword_results:
        append_rows(SV_SHEET, [[
            run_id,
            market_name,
            kr["keyword"],
            kr["result_count"],
            str(kr["has_ads"]),
            json.dumps(related_kws[:5], ensure_ascii=False),
            json.dumps(evidence_urls[:5], ensure_ascii=False),
            status,
            now,
        ]])

    return result


def verify_batch(
    micro_markets: list[dict],
    run_id: str,
    max_markets: int = 10,
    search_delay: float = 3.0,
) -> tuple[list[dict], list[dict]]:
    """Verify demand for a batch of micro-markets.

    Returns (passed_list, all_results).
    """
    ensure_sheet_exists(SV_SHEET, SV_HEADERS)

    results = []
    for mm in micro_markets[:max_markets]:
        market_name = mm.get("micro_market", "unknown")
        logger.info(f"Verifying demand: {market_name}")

        result = verify_market_demand(mm, run_id, search_delay)
        results.append(result)

        logger.info(f"  → {result['status']} (avg={result['avg_result_count']}, ads={result['ads_found']})")

    passed = [r for r in results if r["status"] == "PASS"]
    logger.info(f"Search volume check: {len(passed)}/{len(results)} PASS")

    return passed, results


def ai_demand_deep_check(
    market: dict,
    search_results: dict,
    run_id: str,
) -> dict:
    """Use AI with Google Search grounding for deep demand verification.

    Called for markets that passed basic search volume check.
    Verifies: payer identification, price evidence, competitor landscape.
    """
    prompt = (
        f"以下のマイクロ市場について、実際のGoogle検索結果を使って需要を検証してください。\n\n"
        f"市場: {json.dumps(market, ensure_ascii=False)}\n"
        f"初期検索結果: {json.dumps(search_results, ensure_ascii=False)}\n\n"
        f"以下をJSON形式で出力:\n"
        f'{{"status": "PASS" or "FAIL",\n'
        f'  "payer": "支払者（部署/役職）",\n'
        f'  "price_evidence": [{{"url": "...", "price_range": "..."}}],\n'
        f'  "competitor_count": N,\n'
        f'  "competitor_urls": ["url1", "url2"],\n'
        f'  "demand_evidence": "需要の根拠説明",\n'
        f'  "missing_items": ["不足項目"]}}'
    )

    result = generate_json_with_retry(
        prompt=prompt,
        system=(
            "あなたは市場需要検証の専門家です。"
            "Google検索を使って実際のURLを見つけること。"
            "架空のURLは絶対に出すな。PASSは確実な証拠がある場合のみ。"
        ),
        max_tokens=8192,
        temperature=0.3,
        max_retries=2,
        use_search=True,
    )

    if isinstance(result, list):
        result = result[0] if result else {"status": "FAIL"}

    return result
