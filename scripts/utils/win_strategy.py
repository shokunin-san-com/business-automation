"""
win_strategy.py — Module W: Generate winning strategy for a market.

Analyzes competitor gaps, market positioning, and creates a
differentiation strategy for the 業務代行型 business model.

Uses competitor_20_log + competitor_pricing_log + gap_top3 data.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TEMPLATES_DIR, get_logger
from utils.claude_client import generate_json_with_retry
from utils.sheets_client import get_all_rows, append_rows

logger = get_logger("win_strategy", "win_strategy.log")
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


def generate_win_strategy(
    market_name: str,
    run_id: str,
    gap_top3: list[dict] | None = None,
) -> dict:
    """Generate a winning strategy for a specific market.

    Returns {
        positioning: str,
        differentiation_points: list[str],
        pricing_strategy: str,
        target_messaging: str,
        competitive_moat: str,
        action_items: list[str],
    }
    """
    # Load competitor data
    competitors = []
    pricing_data = []
    try:
        comp_rows = get_all_rows("competitor_20_log")
        competitors = [r for r in comp_rows if r.get("market_name") == market_name]
    except Exception:
        pass

    try:
        price_rows = get_all_rows("competitor_pricing_log")
        pricing_data = [r for r in price_rows if r.get("market_name") == market_name]
    except Exception:
        pass

    # Build context
    comp_summary = []
    for c in competitors[:10]:
        comp_summary.append({
            "name": c.get("company_name", ""),
            "url": c.get("url", ""),
            "price_url": c.get("price_url", ""),
        })

    pricing_summary = []
    for p in pricing_data[:10]:
        if p.get("price_text"):
            pricing_summary.append({
                "company": p.get("company_name", ""),
                "price_range": p.get("price_range", ""),
                "price_text": p.get("price_text", "")[:100],
            })

    prompt = (
        f"以下の市場データに基づいて、業務代行型ビジネスの勝ち筋戦略を策定してください。\n\n"
        f"市場: {market_name}\n"
        f"競合{len(competitors)}社（上位10社）: {json.dumps(comp_summary, ensure_ascii=False)}\n"
        f"価格情報: {json.dumps(pricing_summary, ensure_ascii=False)}\n"
        f"ギャップTOP3: {json.dumps(gap_top3 or [], ensure_ascii=False)}\n\n"
        f"以下のJSON形式で出力:\n"
        f'{{"positioning": "市場でのポジショニング",\n'
        f'  "differentiation_points": ["差別化ポイント1", "差別化ポイント2", "差別化ポイント3"],\n'
        f'  "pricing_strategy": "価格戦略（競合比較含む）",\n'
        f'  "target_messaging": "ターゲットへのメッセージング",\n'
        f'  "competitive_moat": "AI活用による競争優位性",\n'
        f'  "action_items": ["即時アクション1", "即時アクション2", "即時アクション3"]}}\n\n'
        f"制約:\n"
        f"- 業務代行型モデル前提（SaaS/ツール販売禁止）\n"
        f"- 初期費用0円、成果報酬 or 月額固定\n"
        f"- AI活用による低コスト・高速を武器"
    )

    result = generate_json_with_retry(
        prompt=prompt,
        system=(
            "あなたは業務代行ビジネスの戦略コンサルタントです。"
            "実データに基づいて具体的な戦略を立案してください。"
        ),
        max_tokens=4096,
        temperature=0.4,
        max_retries=2,
    )

    if isinstance(result, list):
        result = result[0] if result else {}

    # Save to sheets
    try:
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        append_rows("win_strategy_log", [[
            run_id,
            market_name,
            result.get("positioning", ""),
            json.dumps(result.get("differentiation_points", []), ensure_ascii=False),
            result.get("pricing_strategy", ""),
            result.get("competitive_moat", ""),
            json.dumps(result.get("action_items", []), ensure_ascii=False),
            now,
        ]])
    except Exception as e:
        logger.warning(f"Failed to save win strategy: {e}")

    logger.info(f"Win strategy generated for {market_name}")
    return result
