"""
Company website scraper — find companies and their contact form URLs.

Uses Google search (via requests) and BeautifulSoup to:
1. Search for companies by industry + region
2. Find contact/inquiry form URLs on their websites
"""

import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_logger

logger = get_logger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

CONTACT_PATH_PATTERNS = [
    r"/contact",
    r"/inquiry",
    r"/form",
    r"/お問い合わせ",
    r"/お問合せ",
    r"/toiawase",
    r"/otoiawase",
]


def search_companies(query: str, num_results: int = 10) -> list[dict]:
    """Search for company websites using a query.

    Returns list of {title, url, snippet}.
    """
    results = []
    try:
        params = {"q": query, "num": num_results, "hl": "ja", "gl": "jp"}
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
                if href.startswith("http"):
                    results.append({
                        "title": title_el.get_text(strip=True),
                        "url": href,
                        "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                    })
    except Exception as e:
        logger.error(f"Search failed: {e}")

    logger.info(f"Found {len(results)} search results for: {query}")
    return results


def find_contact_form_url(base_url: str) -> str | None:
    """Crawl a company website to find the contact/inquiry form URL.

    Returns the form URL or None.
    """
    try:
        resp = requests.get(base_url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Check all links on the page
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            text = a.get_text(strip=True).lower()

            # Check href patterns
            for pattern in CONTACT_PATH_PATTERNS:
                if re.search(pattern, href, re.IGNORECASE):
                    return urljoin(base_url, a["href"])

            # Check link text
            if any(kw in text for kw in ["お問い合わせ", "お問合せ", "contact", "相談"]):
                return urljoin(base_url, a["href"])

    except Exception as e:
        logger.warning(f"Failed to crawl {base_url}: {e}")

    return None


def extract_company_name(url: str, soup: BeautifulSoup | None = None) -> str:
    """Try to extract company name from the website."""
    if soup is None:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception:
            return urlparse(url).netloc

    # Try title tag
    title = soup.find("title")
    if title:
        text = title.get_text(strip=True)
        # Common patterns: "会社名 | サイト名" or "会社名 - サイト名"
        for sep in ["|", "｜", "-", "–", "—"]:
            if sep in text:
                return text.split(sep)[0].strip()
        return text[:50]

    return urlparse(url).netloc


def scrape_companies(
    industry: str,
    region: str = "",
    max_results: int = 10,
    delay: float = 2.0,
) -> list[dict]:
    """Full pipeline: search for companies, find contact forms.

    Returns list of {company_name, url, form_url, industry, region}.
    """
    query = f"{industry} {region} 企業 会社".strip()
    search_results = search_companies(query, num_results=max_results)

    companies = []
    for result in search_results:
        url = result["url"]
        logger.info(f"Checking: {url}")

        form_url = find_contact_form_url(url)
        company_name = result["title"]

        companies.append({
            "company_name": company_name,
            "url": url,
            "form_url": form_url or "",
            "industry": industry,
            "region": region,
        })

        time.sleep(delay)  # Be polite

    logger.info(f"Scraped {len(companies)} companies, {sum(1 for c in companies if c['form_url'])} with forms")
    return companies
