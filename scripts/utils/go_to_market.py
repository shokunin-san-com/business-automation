"""
go_to_market.py — Module S: Go-to-market strategy generation.

Creates a concrete GTM plan including:
  - Channel selection (form sales, SNS, blog SEO, ads)
  - Budget allocation per channel
  - Timeline and milestones
  - KPIs and success criteria
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

logger = get_logger("go_to_market", "go_to_market.log")
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


def generate_gtm_plan(
    market_name: str,
    run_id: str,
    offers: list[dict] | None = None,
    win_strategy: dict | None = None,
    monthly_budget: int = 100000,
) -> dict:
    """Generate a go-to-market plan.

    Returns {
        channels: list[{name, allocation_pct, monthly_spend, expected_leads}],
        timeline: list[{week, milestone, actions}],
        kpis: list[{metric, target, measurement}],
        first_week_actions: list[str],
    }
    """
    offer_summary = ""
    if offers:
        for o in offers[:3]:
            offer_summary += (
                f"- {o.get('offer_name', '')}: {o.get('price', '')} "
                f"({o.get('deliverable', '')})\n"
            )

    strategy_summary = ""
    if win_strategy:
        strategy_summary = (
            f"ポジショニング: {win_strategy.get('positioning', '')}\n"
            f"価格戦略: {win_strategy.get('pricing_strategy', '')}"
        )

    prompt = (
        f"以下の情報に基づいてGo-to-Market計画を策定してください。\n\n"
        f"市場: {market_name}\n"
        f"月間予算: ¥{monthly_budget:,}\n"
        f"オファー:\n{offer_summary}\n"
        f"戦略:\n{strategy_summary}\n\n"
        f"利用可能チャネル:\n"
        f"1. フォーム営業（Playwright自動送信）\n"
        f"2. SNS投稿（Twitter/LinkedIn自動投稿）\n"
        f"3. ブログSEO（AI記事自動生成）\n"
        f"4. LP（Vercel自動デプロイ）\n\n"
        f"以下のJSON形式で出力:\n"
        f'{{"channels": [{{"name": "チャネル名", "allocation_pct": 30, '
        f'"monthly_spend": 30000, "expected_leads": 10}}],\n'
        f'  "timeline": [{{"week": 1, "milestone": "マイルストーン", "actions": ["アクション"]}}],\n'
        f'  "kpis": [{{"metric": "KPI名", "target": "目標値", "measurement": "測定方法"}}],\n'
        f'  "first_week_actions": ["初週アクション1", "初週アクション2"]}}\n\n'
        f"制約:\n"
        f"- 全チャネルAI自動化前提\n"
        f"- 人的工数は最小限（CEO1人運用）\n"
        f"- 初週から実行可能なアクションを優先"
    )

    result = generate_json_with_retry(
        prompt=prompt,
        system=(
            "あなたはBtoBマーケティングの専門家です。"
            "AI自動化チャネルを活用した現実的なGTM計画を立案してください。"
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
        append_rows("gtm_plan_log", [[
            run_id,
            market_name,
            json.dumps(result.get("channels", []), ensure_ascii=False),
            json.dumps(result.get("timeline", []), ensure_ascii=False),
            json.dumps(result.get("kpis", []), ensure_ascii=False),
            json.dumps(result.get("first_week_actions", []), ensure_ascii=False),
            str(monthly_budget),
            now,
        ]])
    except Exception as e:
        logger.warning(f"Failed to save GTM plan: {e}")

    logger.info(f"GTM plan generated for {market_name}")
    return result
