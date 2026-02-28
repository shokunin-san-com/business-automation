"""
target_collector.py — Collect target companies for form-based outreach.

Enhanced version of scraper.py, purpose-built for form_sales_targets.
- Multiple search query patterns per market
- Google search pagination (pages 1-3)
- Dedup against existing targets in Sheets
- Batch registration to form_sales_targets
- Header/footer/sitemap contact form detection
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_logger
from utils.sheets_client import get_all_rows, append_rows

logger = get_logger("target_collector", "target_collector.log")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

CONTACT_PATH_PATTERNS = [
    r"/contact",
    r"/inquiry",
    r"/form",
    r"/お問い合わせ",
    r"/お問合せ",
    r"/toiawase",
    r"/otoiawase",
    r"/soudan",
    r"/相談",
    r"/estimate",
    r"/見積",
    r"/request",
]

CONTACT_LINK_KEYWORDS = [
    "お問い合わせ", "お問合せ", "contact", "相談", "資料請求",
    "見積", "無料相談", "ご依頼", "お申し込み",
]

# Exclude domains that are NOT company websites
EXCLUDE_DOMAINS = {
    "google.com", "google.co.jp", "youtube.com", "facebook.com",
    "twitter.com", "x.com", "instagram.com", "linkedin.com",
    "wikipedia.org", "amazon.co.jp", "amazon.com", "rakuten.co.jp",
    "yahoo.co.jp", "note.com", "qiita.com", "zenn.dev",
    "wantedly.com", "en-japan.com", "mynavi.jp", "rikunabi.com",
}


def _is_company_domain(url: str) -> bool:
    domain = urlparse(url).netloc.lower()
    for ex in EXCLUDE_DOMAINS:
        if domain.endswith(ex):
            return False
    return True


def _search_google(query: str, num_results: int = 10, start: int = 0) -> list[dict]:
    """Search Google and return list of {title, url, snippet}."""
    results = []
    try:
        params = {
            "q": query,
            "num": num_results,
            "start": start,
            "hl": "ja",
            "gl": "jp",
        }
        resp = requests.get(
            "https://www.google.com/search",
            params=params,
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for g in soup.select("div.g"):
            link = g.select_one("a[href]")
            title_el = g.select_one("h3")
            snippet_el = g.select_one("div.VwiC3b")
            if link and title_el:
                href = link.get("href", "")
                if href.startswith("http") and _is_company_domain(href):
                    results.append({
                        "title": title_el.get_text(strip=True),
                        "url": href,
                        "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                    })
    except Exception as e:
        logger.error(f"Google search failed (start={start}): {e}")

    return results


def _find_contact_form(base_url: str) -> str | None:
    """Find contact/inquiry form URL from a company website.

    Strategy: check homepage links → common paths → sitemap.
    """
    try:
        resp = requests.get(base_url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 1. Check all links (header, footer, nav, body)
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            text = a.get_text(strip=True).lower()

            for pattern in CONTACT_PATH_PATTERNS:
                if re.search(pattern, href, re.IGNORECASE):
                    return urljoin(base_url, a["href"])

            if any(kw in text for kw in CONTACT_LINK_KEYWORDS):
                return urljoin(base_url, a["href"])

        # 2. Try common paths directly
        parsed = urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        common_paths = ["/contact", "/contact/", "/inquiry", "/お問い合わせ", "/form"]
        for path in common_paths:
            try:
                check_url = origin + path
                r = requests.head(check_url, headers=HEADERS, timeout=5, allow_redirects=True)
                if r.status_code == 200:
                    return check_url
            except Exception:
                continue

    except Exception as e:
        logger.warning(f"Failed to crawl {base_url}: {e}")

    return None


def _build_queries(market_name: str, payer: str) -> list[str]:
    """Build multiple search queries for a market."""
    queries = []

    # Primary: direct industry search
    queries.append(f"{market_name} 企業 会社 お問い合わせ")

    # Payer-targeted
    if payer:
        queries.append(f"{payer} 向け サービス 企業")

    # Regional variants
    for region in ["東京", "大阪", "全国"]:
        queries.append(f"{market_name} {region} 企業")

    return queries


def _get_existing_urls() -> set[str]:
    """Get all URLs already in form_sales_targets to avoid duplicates."""
    try:
        rows = get_all_rows("form_sales_targets")
        urls = set()
        for r in rows:
            if r.get("url"):
                urls.add(r["url"])
            if r.get("form_url"):
                urls.add(r["form_url"])
        return urls
    except Exception as e:
        logger.warning(f"Failed to read existing targets: {e}")
        return set()


def collect_targets(
    business_id: str,
    market_name: str,
    payer: str = "",
    target_count: int = 20,
    search_delay: float = 3.0,
    crawl_delay: float = 1.5,
) -> list[dict]:
    """Collect target companies for a single business/LP.

    Args:
        business_id: run_id or business identifier
        market_name: micro-market name (e.g., "塗装業 AI見積もり")
        payer: who pays (e.g., "塗装会社の経営者")
        target_count: number of targets to collect (default 20)
        search_delay: seconds between Google searches
        crawl_delay: seconds between company crawls

    Returns:
        List of collected company dicts.
    """
    logger.info(f"Collecting {target_count} targets for: {market_name} (bid={business_id[:8]})")

    existing_urls = _get_existing_urls()
    queries = _build_queries(market_name, payer)
    seen_domains: set[str] = set()
    collected: list[dict] = []

    for query in queries:
        if len(collected) >= target_count:
            break

        # Search up to 3 pages
        for page in range(3):
            if len(collected) >= target_count:
                break

            start = page * 10
            logger.info(f"Searching: '{query}' (page {page + 1})")
            results = _search_google(query, num_results=10, start=start)

            if not results:
                break

            for result in results:
                if len(collected) >= target_count:
                    break

                url = result["url"]
                domain = urlparse(url).netloc.lower()

                # Skip if already in targets or same domain already collected
                if url in existing_urls or domain in seen_domains:
                    continue

                # Crawl for contact form
                form_url = _find_contact_form(url)
                if not form_url:
                    logger.debug(f"No form found: {url}")
                    time.sleep(crawl_delay)
                    continue

                company = {
                    "business_id": business_id,
                    "company_name": result["title"],
                    "url": url,
                    "form_url": form_url,
                    "industry": market_name,
                    "region": "",
                    "message": "",
                    "status": "pending",
                    "contacted_at": "",
                    "response": "",
                }
                collected.append(company)
                seen_domains.add(domain)
                existing_urls.add(url)
                existing_urls.add(form_url)

                logger.info(f"  [{len(collected)}/{target_count}] {result['title']} → {form_url}")
                time.sleep(crawl_delay)

            time.sleep(search_delay)

    logger.info(f"Collected {len(collected)} targets for {market_name}")
    return collected


def register_targets(targets: list[dict]) -> int:
    """Write collected targets to form_sales_targets sheet.

    Returns number of rows written.
    """
    if not targets:
        return 0

    rows = []
    for t in targets:
        rows.append([
            t["business_id"],
            t["company_name"],
            t["url"],
            t["form_url"],
            t["industry"],
            t.get("region", ""),
            "",  # message
            "pending",
            "",  # contacted_at
            "",  # response
        ])

    append_rows("form_sales_targets", rows)
    logger.info(f"Registered {len(rows)} targets to form_sales_targets")
    return len(rows)


def collect_and_register(
    business_id: str,
    market_name: str,
    payer: str = "",
    target_count: int = 20,
) -> int:
    """Full pipeline: collect + register for one business.

    Returns number of new targets registered.
    """
    targets = collect_targets(
        business_id=business_id,
        market_name=market_name,
        payer=payer,
        target_count=target_count,
    )
    return register_targets(targets)


def collect_all_active(target_per_lp: int = 20) -> dict:
    """Collect targets for ALL active V2 markets.

    Returns {"total": N, "per_market": {name: count}}.
    """
    from utils.v2_markets import get_active_v2_markets

    markets = get_active_v2_markets()
    if not markets:
        logger.info("No active markets found")
        return {"total": 0, "per_market": {}}

    result = {"total": 0, "per_market": {}}

    for m in markets:
        count = collect_and_register(
            business_id=m["id"],
            market_name=m["name"],
            payer=m.get("payer", ""),
            target_count=target_per_lp,
        )
        result["per_market"][m["name"]] = count
        result["total"] += count

    logger.info(f"Total targets collected: {result['total']} across {len(markets)} markets")
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Collect form sales targets")
    parser.add_argument("--all", action="store_true", help="Collect for all active markets")
    parser.add_argument("--business-id", help="Target business ID")
    parser.add_argument("--market", help="Market name")
    parser.add_argument("--payer", default="", help="Payer description")
    parser.add_argument("--count", type=int, default=20, help="Targets per market")
    args = parser.parse_args()

    if args.all:
        result = collect_all_active(target_per_lp=args.count)
        print(f"Collected {result['total']} targets: {result['per_market']}")
    elif args.business_id and args.market:
        n = collect_and_register(
            business_id=args.business_id,
            market_name=args.market,
            payer=args.payer,
            target_count=args.count,
        )
        print(f"Collected {n} targets for {args.market}")
    else:
        parser.print_help()
