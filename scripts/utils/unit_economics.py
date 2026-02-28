"""
Unit economics calculation module.

Uses AI to estimate LTV, CAC, BEP, and related metrics
based on market research, competitor analysis, and business ideas.

Enhanced for 業務代行型 model:
  - Integrates real competitor pricing data
  - Calculates 業務代行 specific metrics (monthly recurring, churn, delivery cost)
  - Logs results to sheets for pipeline traceability
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TEMPLATES_DIR, get_logger
from utils.claude_client import generate_json_with_retry
from utils.sheets_client import get_all_rows, append_rows
from utils.validators import validate_unit_economics

logger = get_logger(__name__)
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

UE_SHEET = "unit_economics_log"
UE_HEADERS = [
    "run_id", "market_name", "offer_name", "pricing_model",
    "monthly_price", "ltv", "cac", "ltv_cac_ratio",
    "bep_months", "gross_margin_pct", "delivery_cost_pct",
    "calculated_at",
]


def _load_competitor_pricing(market_name: str) -> list[dict]:
    """Load real competitor pricing data from sheets."""
    try:
        rows = get_all_rows("competitor_pricing_log")
        return [r for r in rows if r.get("market_name") == market_name and r.get("price_text")]
    except Exception:
        return []


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


def calculate_agency_ue(
    market_name: str,
    run_id: str,
    offers: list[dict] | None = None,
    competitor_pricing: list[dict] | None = None,
) -> list[dict]:
    """Calculate unit economics for 業務代行型 offers.

    Integrates real competitor pricing and calculates agency-specific metrics.

    Returns list of dicts: {
        offer_name, pricing_model, monthly_price, ltv, cac,
        ltv_cac_ratio, bep_months, gross_margin_pct, delivery_cost_pct,
        monthly_revenue_target, assumptions, risks
    }
    """
    if not offers:
        logger.warning("No offers provided for agency UE calculation.")
        return []

    if competitor_pricing is None:
        competitor_pricing = _load_competitor_pricing(market_name)

    pricing_context = ""
    for p in competitor_pricing[:10]:
        pricing_context += (
            f"\n- {p.get('company_name', '')}: "
            f"価格帯={p.get('price_range', 'N/A')}, "
            f"詳細={p.get('price_text', '')[:80]}"
        )

    offers_context = ""
    for o in offers:
        offers_context += (
            f"\n### {o.get('offer_name', o.get('name', ''))}\n"
            f"価格: {o.get('price', 'N/A')}\n"
            f"納品物: {o.get('deliverable', 'N/A')}\n"
            f"ターゲット: {o.get('target', 'N/A')}\n"
        )

    prompt = (
        f"以下の業務代行型オファーのユニットエコノミクスを算出してください。\n\n"
        f"市場: {market_name}\n"
        f"オファー:\n{offers_context}\n"
        f"競合価格データ:\n{pricing_context}\n\n"
        f"以下のJSON配列形式で出力:\n"
        f'[{{"offer_name": "オファー名", "pricing_model": "月額固定/成果報酬/ハイブリッド",\n'
        f'  "monthly_price": 50000, "ltv": 600000, "cac": 30000,\n'
        f'  "ltv_cac_ratio": 20.0, "bep_months": 1,\n'
        f'  "gross_margin_pct": 80, "delivery_cost_pct": 15,\n'
        f'  "monthly_revenue_target": 500000,\n'
        f'  "assumptions": ["仮定1", "仮定2"],\n'
        f'  "risks": ["リスク1", "リスク2"]}}]\n\n'
        f"制約:\n"
        f"- 業務代行型（初期費用0円、月額固定 or 成果報酬）\n"
        f"- AI活用で delivery_cost は低め（10-20%目安）\n"
        f"- CAC はフォーム営業+SNS前提で保守的に算出\n"
        f"- LTV/CAC >= 3 が健全ライン"
    )

    result = generate_json_with_retry(
        prompt=prompt,
        system=(
            "あなたは業務代行ビジネスのファイナンス専門家です。"
            "実際の競合価格データに基づいて保守的にユニットエコノミクスを算出してください。"
            "必ずJSON配列で出力してください。"
        ),
        max_tokens=8192,
        temperature=0.3,
        max_retries=2,
    )

    if isinstance(result, dict):
        result = [result]

    # Save to sheets
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        rows = []
        for ue in result:
            rows.append([
                run_id,
                market_name,
                ue.get("offer_name", ""),
                ue.get("pricing_model", ""),
                str(ue.get("monthly_price", "")),
                str(ue.get("ltv", "")),
                str(ue.get("cac", "")),
                str(ue.get("ltv_cac_ratio", "")),
                str(ue.get("bep_months", "")),
                str(ue.get("gross_margin_pct", "")),
                str(ue.get("delivery_cost_pct", "")),
                now,
            ])
        if rows:
            append_rows(UE_SHEET, rows)
    except Exception as e:
        logger.warning(f"Failed to save agency UE: {e}")

    logger.info(f"Agency UE calculated for {market_name}: {len(result)} offers")
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
