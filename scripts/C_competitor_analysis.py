"""
C_competitor_analysis.py — V2: 20-company fixed-template competitor analysis.

Reads PASS markets from gate_decision_log (or ACTIVE exploration lane),
analyzes 20 competitors with 7 URL types each, identifies top-3 gaps.
Outputs to competitor_20_log sheet.

All scoring is **prohibited**. URLs must be real or left empty.

Schedule: triggered by orchestrate_v2.py after A1-deep gate passes
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import TEMPLATES_DIR, get_logger
from utils.claude_client import generate_json_with_retry
from utils.sheets_client import get_all_rows, append_rows
from utils.slack_notifier import send_message as slack_notify
from utils.status_writer import update_status
from utils.pdf_knowledge import get_knowledge_summary
from utils.validators import validate_competitor_20

logger = get_logger("competitor_analysis", "competitor_analysis.log")
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

# Pricing scraping
import re
import time as _time
import requests
from bs4 import BeautifulSoup

SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
PRICING_SHEET = "competitor_pricing_log"
PRICING_HEADERS = [
    "run_id", "market_name", "company_name", "company_url",
    "price_url", "price_text", "price_range", "scraped_at",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_settings() -> dict:
    rows = get_all_rows("settings")
    return {r["key"]: r["value"] for r in rows}


def _get_pass_market(run_id: str | None = None) -> dict | None:
    """Get the PASS market from gate_decision_log for this run.

    If no run_id given, uses the latest PASS record.
    Falls back to ACTIVE exploration lane if no PASS found.
    """
    try:
        rows = get_all_rows("gate_decision_log")
        pass_rows = [r for r in rows if r.get("status") == "PASS"]
        if run_id:
            pass_rows = [r for r in pass_rows if r.get("run_id") == run_id]
        if pass_rows:
            return pass_rows[-1]  # latest
    except Exception:
        pass

    # Fallback: check exploration_lane_log for ACTIVE
    try:
        lanes = get_all_rows("exploration_lane_log")
        active = [l for l in lanes if l.get("status") == "ACTIVE"]
        if run_id:
            active = [l for l in active if l.get("run_id") == run_id]
        if active:
            lane = active[-1]
            return {
                "micro_market": lane.get("market", ""),
                "status": "ACTIVE_EXPLORATION",
                "run_id": lane.get("run_id", ""),
            }
    except Exception:
        pass

    return None


def _get_gate_result(run_id: str, micro_market: str) -> dict:
    """Fetch the full gate result from gate_decision_log for context."""
    try:
        rows = get_all_rows("gate_decision_log")
        for r in rows:
            if r.get("run_id") == run_id and r.get("micro_market") == micro_market:
                return r
    except Exception:
        pass
    return {}


def _already_analyzed(run_id: str) -> bool:
    """Check if competitor analysis already exists for this run."""
    try:
        rows = get_all_rows("competitor_20_log")
        return any(r.get("run_id") == run_id for r in rows)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Pricing scraper
# ---------------------------------------------------------------------------

def _scrape_price_from_url(url: str) -> dict:
    """Scrape pricing information from a competitor's price page.

    Returns {price_text, price_range} or empty strings on failure.
    """
    if not url or not url.startswith("http"):
        return {"price_text": "", "price_range": ""}

    try:
        resp = requests.get(url, headers=SCRAPE_HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove script/style tags
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)

        # Find price patterns: ¥XX,XXX / XX万円 / XX,XXX円
        price_patterns = [
            r"¥[\d,]+",
            r"[\d,]+円",
            r"\d+万円",
            r"月額[\d,]+円",
            r"初期費用[\d,]+円",
            r"[\d,]+円[/／]月",
            r"[\d.]+万円[/／]月",
        ]

        found_prices = []
        for pattern in price_patterns:
            matches = re.findall(pattern, text)
            found_prices.extend(matches[:5])

        if found_prices:
            price_text = " | ".join(found_prices[:5])
            # Determine range
            nums = []
            for p in found_prices:
                n = re.findall(r"[\d.]+", p.replace(",", ""))
                if n:
                    val = float(n[0])
                    if "万" in p:
                        val *= 10000
                    nums.append(val)
            if nums:
                low, high = min(nums), max(nums)
                price_range = f"¥{int(low):,}〜¥{int(high):,}" if low != high else f"¥{int(low):,}"
            else:
                price_range = ""
            return {"price_text": price_text, "price_range": price_range}

    except Exception as e:
        logger.warning(f"Price scrape failed for {url}: {e}")

    return {"price_text": "", "price_range": ""}


def scrape_competitor_pricing(
    competitors: list[dict],
    run_id: str,
    market_name: str,
    max_scrape: int = 20,
    delay: float = 1.5,
) -> list[dict]:
    """Scrape pricing from competitor price_url pages.

    Saves results to competitor_pricing_log sheet.
    Returns list of pricing results.
    """
    from utils.sheets_client import ensure_sheet_exists
    ensure_sheet_exists(PRICING_SHEET, PRICING_HEADERS)

    results = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows_to_save = []

    for comp in competitors[:max_scrape]:
        company = comp.get("company_name", "")
        price_url = comp.get("price_url", "")

        if not price_url:
            results.append({"company_name": company, "price_text": "", "price_range": ""})
            continue

        logger.info(f"Scraping price: {company} → {price_url[:60]}")
        pricing = _scrape_price_from_url(price_url)
        pricing["company_name"] = company

        rows_to_save.append([
            run_id, market_name, company,
            comp.get("url", ""), price_url,
            pricing["price_text"][:200],
            pricing["price_range"],
            now,
        ])

        results.append(pricing)
        _time.sleep(delay)

    if rows_to_save:
        from utils.sheets_client import append_rows as _append
        _append(PRICING_SHEET, rows_to_save)
        logger.info(f"Saved {len(rows_to_save)} pricing records")

    scraped = sum(1 for r in results if r.get("price_text"))
    logger.info(f"Pricing scraped: {scraped}/{len(results)} competitors had price data")

    return results


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze_competitors_20(
    micro_market: dict,
    gate_result: dict,
    knowledge_context: str,
    run_id: str,
) -> dict:
    """Analyze 20 competitors with 7 URL types each.

    Returns dict with 'competitors' list and 'gap_top3' list.
    """
    template = jinja_env.get_template("competitor_20_prompt.j2")
    prompt = template.render(
        micro_market_json=json.dumps(micro_market, ensure_ascii=False),
        gate_result_json=json.dumps(gate_result, ensure_ascii=False),
        knowledge_context=knowledge_context,
    )

    result = generate_json_with_retry(
        prompt=prompt,
        system=(
            "あなたは競合分析の専門家です。"
            "スコアを出すな。架空の企業名・URLは絶対に出すな。"
            "20社固定で分析し、各社に7種のURLを付与すること。"
            "URLが見つからない場合は空文字にする。"
            "必ず指定のJSONオブジェクトフォーマットで出力してください。"
        ),
        max_tokens=16384,
        temperature=0.3,
        max_retries=3,
        validator=validate_competitor_20,
    )

    # Validator now always returns {"competitors": [...], "gap_top3": [...]}
    # Handle edge cases where result may still be a raw list or unexpected format
    if isinstance(result, list):
        result = {"competitors": result, "gap_top3": []}
    elif isinstance(result, dict) and "competitors" not in result:
        result = {"competitors": [], "gap_top3": []}

    return result


def save_competitors_to_sheets(
    analysis: dict,
    run_id: str,
    market_name: str,
) -> int:
    """Save 20 competitors to competitor_20_log sheet."""
    competitors = analysis.get("competitors", [])
    rows: list[list] = []

    for comp in competitors:
        rows.append([
            run_id,
            market_name,
            comp.get("company_name", ""),
            comp.get("url", ""),
            comp.get("price_url", ""),
            comp.get("case_url", ""),
            comp.get("hire_url", ""),
            comp.get("ad_url", ""),
            comp.get("expo_url", ""),
            comp.get("update_url", ""),
        ])

    if rows:
        append_rows("competitor_20_log", rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main(run_id: str | None = None):
    """
    V2 Competitor Analysis: 20-company fixed template.

    Can be called standalone or from orchestrate_v2.py with a shared run_id.
    """
    logger.info("=== V2 Competitor analysis start ===")
    update_status("C_competitor_analysis", "running", "V2競合分析を開始...")

    try:
        knowledge_context = get_knowledge_summary()

        # Get the PASS market
        pass_market = _get_pass_market(run_id)
        if not pass_market:
            msg = "PASS市場なし。gate_decision_logにPASSレコードが存在しません"
            logger.info(msg)
            update_status("C_competitor_analysis", "success", msg,
                          {"competitors_analyzed": 0})
            return {"competitors": [], "gap_top3": []}

        market_name = pass_market.get("micro_market", "unknown")
        effective_run_id = run_id or pass_market.get("run_id", "")

        # Skip if already analyzed
        if effective_run_id and _already_analyzed(effective_run_id):
            msg = f"run_id={effective_run_id[:8]} は分析済み。スキップ"
            logger.info(msg)
            update_status("C_competitor_analysis", "success", msg)
            return {"competitors": [], "gap_top3": []}

        logger.info(f"Analyzing 20 competitors for: {market_name}")
        update_status("C_competitor_analysis", "running", f"20社分析中: {market_name}")

        # Get gate result for context
        gate_result = _get_gate_result(effective_run_id, market_name)

        # Build micro_market dict for prompt
        micro_market_data = {
            "micro_market": market_name,
            "payer": pass_market.get("payer", ""),
            "evidence_urls": pass_market.get("evidence_urls", ""),
            "blackout_hypothesis": pass_market.get("blackout_hypothesis", ""),
        }

        # Run analysis
        analysis = analyze_competitors_20(
            micro_market_data, gate_result, knowledge_context, effective_run_id
        )

        # Save to sheets
        count = save_competitors_to_sheets(analysis, effective_run_id, market_name)

        # Phase 2: Scrape actual pricing from competitor websites
        competitors = analysis.get("competitors", [])
        pricing_results = []
        if competitors:
            logger.info(f"Phase 2: Scraping pricing for {len(competitors)} competitors...")
            update_status("C_competitor_analysis", "running", f"価格スクレイピング中: {market_name}")
            pricing_results = scrape_competitor_pricing(
                competitors, effective_run_id, market_name
            )

        gap_top3 = analysis.get("gap_top3", [])
        gap_summary = " / ".join(
            g.get("gap", "")[:30] for g in gap_top3[:3]
        ) if gap_top3 else "ギャップ未検出"

        pricing_count = sum(1 for p in pricing_results if p.get("price_text"))

        if count > 0:
            slack_notify(
                f":crossed_swords: V2競合分析完了: *{market_name}*\n"
                f"  {count}社を分析 | 価格取得{pricing_count}社\n"
                f"  穴トップ3: {gap_summary}"
            )

        update_status(
            "C_competitor_analysis", "success",
            f"{count}社分析 | 穴: {gap_summary}",
            {
                "run_id": effective_run_id,
                "competitors_analyzed": count,
                "gap_count": len(gap_top3),
            },
        )

        logger.info(f"=== V2 Competitor analysis complete: {count} competitors ===")

        return {
            "run_id": effective_run_id,
            "market_name": market_name,
            "competitors": analysis.get("competitors", []),
            "gap_top3": gap_top3,
        }

    except Exception as e:
        update_status("C_competitor_analysis", "error", str(e))
        logger.error(f"V2 Competitor analysis failed: {e}")
        raise


if __name__ == "__main__":
    main()
