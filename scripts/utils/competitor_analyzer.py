"""
competitor_analyzer.py — Gemini grounding-based competitor analysis.

Key design decisions (v2):
  - No competitors found = FAIL (no market exists)
  - Price scraping REMOVED — rely on Gemini grounding only
  - 3-axis win assessment: gap / marketing / ai_cost
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta

from jinja2 import Environment, FileSystemLoader

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TEMPLATES_DIR, get_logger
from utils.claude_client import generate_json_with_retry
from utils.sheets_client import append_rows

logger = get_logger("competitor_analyzer", "competitor_analyzer.log")
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

JST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# Competitor Discovery (Gemini Grounding)
# ---------------------------------------------------------------------------

def _discover_competitors(market_name: str, max_count: int = 20) -> list[dict]:
    prompt = (
        f"「{market_name}」の市場で事業を行っている日本の企業・サービスを"
        f"{max_count}社リストアップしてください。\n\n"
        f"各社について以下を調べてください:\n"
        f"- 企業名（正式名称）\n"
        f"- 公式サイトURL\n"
        f"- 料金ページURL（あれば）\n"
        f"- 導入事例ページURL（あれば）\n"
        f"- 採用ページURL（あれば）\n"
        f"- 広告出稿の有無\n\n"
        f"実在する企業のみ。架空の企業は絶対に出さないこと。\n"
        f"URLは実在するページのみ記載すること。\n\n"
        f"JSON配列で出力:\n"
        f'[{{"company_name": "企業名", "url": "https://...", '
        f'"price_url": "", "case_url": "", "hire_url": "", '
        f'"ad_url": "", "update_url": ""}}]'
    )

    result = generate_json_with_retry(
        prompt=prompt,
        system="実在する企業とURLのみを出力してください。",
        max_tokens=16384,
        temperature=0.2,
        max_retries=2,
        use_search=True,
    )

    if isinstance(result, dict):
        result = [result]

    valid = [c for c in result if isinstance(c, dict) and c.get("company_name")]
    logger.info(f"競合発見: {market_name} → {len(valid)}社")
    return valid


# ---------------------------------------------------------------------------
# Win Assessment (3-axis)
# ---------------------------------------------------------------------------

def _assess_win_strategy(market_name: str, competitors: list[dict]) -> dict:
    template = jinja_env.get_template("win_assessment_prompt.j2")

    comp_summary = json.dumps(
        [{"company_name": c["company_name"], "url": c.get("url", "")} for c in competitors[:20]],
        ensure_ascii=False,
    )

    from utils.exploration_engine import CONSTRUCTION_CONTEXT

    prompt = template.render(
        market_name=market_name,
        competitors_json=comp_summary,
        construction_context=CONSTRUCTION_CONTEXT,
    )

    result = generate_json_with_retry(
        prompt=prompt,
        system="客観的に勝ち筋を判定してください。",
        max_tokens=4096,
        temperature=0.3,
        max_retries=2,
        use_search=True,
    )

    if isinstance(result, list):
        result = result[0] if result else {}

    return result


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

def analyze_competitors(
    market_name: str,
    run_id: str,
    max_competitors: int = 20,
) -> dict:
    """Analyze competitors for a market.

    Returns:
        {
            "status": "PASS" / "FAIL",
            "fail_reason": "..." (if FAIL),
            "competitors": [...],
            "win_assessment": {...},
        }
    """
    # Discover competitors
    competitors = _discover_competitors(market_name, max_competitors)

    # Save competitors to sheet
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for c in competitors:
        rows.append([
            run_id,
            market_name,
            c.get("company_name", ""),
            c.get("url", ""),
            c.get("price_url", ""),
            c.get("case_url", ""),
            c.get("hire_url", ""),
            c.get("ad_url", ""),
            "",  # expo_url
            c.get("update_url", ""),
        ])
    if rows:
        try:
            append_rows("competitor_20_log", rows)
        except Exception as e:
            logger.warning(f"Failed to save competitors: {e}")

    # No competitors = no market = FAIL
    if len(competitors) == 0:
        logger.warning(f"競合ゼロ: {market_name} → FAIL (市場なし)")
        return {
            "status": "FAIL",
            "fail_reason": "競合が見つからない = 市場が存在しない",
            "competitors": [],
            "win_assessment": {},
        }

    # Cost tracking
    try:
        from utils.cost_tracker import record_api_call
        record_api_call(
            run_id=run_id, phase="D_competitor",
            input_tokens=2000, output_tokens=5000,
            used_search=True,
            note=f"discovery: {market_name}",
        )
    except Exception:
        pass

    # Win assessment (3-axis)
    time.sleep(1.0)
    win = _assess_win_strategy(market_name, competitors)

    try:
        from utils.cost_tracker import record_api_call
        record_api_call(
            run_id=run_id, phase="D_competitor",
            input_tokens=2000, output_tokens=2000,
            used_search=True,
            note=f"win_assessment: {market_name}",
        )
    except Exception:
        pass

    verdict = win.get("overall_verdict", "NOT_WINNABLE")

    if verdict == "NOT_WINNABLE":
        logger.info(f"勝ち筋なし: {market_name} → FAIL")
        return {
            "status": "FAIL",
            "fail_reason": "勝ち筋3軸すべてなし",
            "competitors": competitors,
            "win_assessment": win,
        }

    logger.info(f"競合分析PASS: {market_name} ({len(competitors)}社, {verdict})")
    return {
        "status": "PASS",
        "competitors": competitors,
        "win_assessment": win,
    }
