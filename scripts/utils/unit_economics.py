"""
Unit economics calculation module.

Uses AI to estimate LTV, CAC, BEP, and related metrics
based on market research, competitor analysis, and business ideas.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TEMPLATES_DIR, get_logger
from utils.claude_client import generate_json_with_retry
from utils.validators import validate_unit_economics

logger = get_logger(__name__)
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


def calculate(
    ideas: list[dict],
    market_data: list[dict] | None = None,
    competitor_data: list[dict] | None = None,
    ceo_profile: str = "",
) -> list[dict]:
    """Calculate unit economics for each business idea.

    Args:
        ideas: Business ideas from Step 0.
        market_data: Market research data for context.
        competitor_data: Competitor analysis data for pricing benchmarks.
        ceo_profile: CEO profile for capability assessment.

    Returns:
        List of UE dicts per idea: {
            idea_name, ltv, cac, ltv_cac_ratio, bep_months,
            bep_customers, initial_investment, pricing_model,
            monthly_revenue_target, gross_margin_pct,
            assumptions, risks
        }
    """
    if not ideas:
        logger.warning("No ideas provided for UE calculation.")
        return []

    # Build context strings
    market_context = ""
    if market_data:
        for m in market_data:
            market_context += (
                f"\n- {m.get('market_name', '')}: "
                f"TAM={m.get('market_size_tam', 'N/A')}, "
                f"SAM={m.get('market_size_sam', 'N/A')}, "
                f"成長率={m.get('growth_rate', 'N/A')}"
            )

    competitor_context = ""
    if competitor_data:
        for c in competitor_data:
            competitor_context += (
                f"\n- {c.get('competitor_name', '')}: "
                f"価格={c.get('pricing_model', 'N/A')}, "
                f"シェア={c.get('market_share_estimate', 'N/A')}, "
                f"強み={c.get('strengths', 'N/A')}"
            )

    ideas_context = ""
    for idea in ideas:
        ideas_context += (
            f"\n### {idea.get('name', '')}\n"
            f"カテゴリ: {idea.get('category', '')}\n"
            f"概要: {idea.get('description', '')}\n"
            f"ターゲット: {idea.get('target_audience', '')}\n"
            f"差別化: {idea.get('differentiator', '')}\n"
            f"市場規模: {idea.get('market_size', '')}\n"
        )

    template = jinja_env.get_template("unit_economics_prompt.j2")
    prompt = template.render(
        ideas_context=ideas_context,
        market_context=market_context,
        competitor_context=competitor_context,
        ceo_profile=ceo_profile,
        num_ideas=len(ideas),
    )

    def _validator(data):
        return validate_unit_economics(data)

    result = generate_json_with_retry(
        prompt=prompt,
        system=(
            "あなたはスタートアップのファイナンス専門家です。"
            "ユニットエコノミクス（LTV/CAC/BEP）の算出に精通しています。"
            "保守的な前提で計算し、楽観的すぎる数値は避けてください。"
            "必ずJSON配列で出力してください。"
            "各フィールドの計算式（calculation）は50文字以内で簡潔に。"
        ),
        max_tokens=16384,
        temperature=0.3,
        max_retries=2,
        validator=_validator,
    )

    if isinstance(result, dict):
        result = [result]

    logger.info(f"Calculated unit economics for {len(result)} ideas")
    return result


def format_ue_summary(ue_data: list[dict]) -> str:
    """Format UE data as human-readable summary for notifications."""
    if not ue_data:
        return "ユニットエコノミクス: データなし"

    lines = []
    for ue in ue_data:
        name = ue.get("idea_name", "不明")
        ltv = ue.get("ltv", "N/A")
        cac = ue.get("cac", "N/A")
        ratio = ue.get("ltv_cac_ratio", "N/A")
        bep = ue.get("bep_months", "N/A")
        pricing = ue.get("pricing_model", "N/A")

        health = "🟢" if isinstance(ratio, (int, float)) and ratio >= 3 else "🟡" if isinstance(ratio, (int, float)) and ratio >= 1 else "🔴"

        lines.append(
            f"{health} *{name}*\n"
            f"  LTV: ¥{ltv:,} | CAC: ¥{cac:,} | LTV/CAC: {ratio}x\n"
            f"  BEP: {bep}ヶ月 | 価格モデル: {pricing}"
            if isinstance(ltv, (int, float)) and isinstance(cac, (int, float))
            else f"{health} *{name}*\n  LTV: {ltv} | CAC: {cac} | LTV/CAC: {ratio} | BEP: {bep}ヶ月"
        )

    return "\n".join(lines)
