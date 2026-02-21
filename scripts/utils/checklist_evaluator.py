"""
Checklist evaluator — automatically evaluates business ideas against
the 0→1 Checklist (84 items) and Strategy Checklist (80 items).

Uses AI to answer each applicable checklist question based on
available pipeline data (market research, competitors, UE, etc.).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TEMPLATES_DIR, DATA_DIR, get_logger
from utils.claude_client import generate_json_with_retry
from utils.validators import validate_checklist_evaluation

logger = get_logger(__name__)
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

CHECKLIST_0TO1_PATH = DATA_DIR / "checklist_0to1.json"
CHECKLIST_STRATEGY_PATH = DATA_DIR / "checklist_strategy.json"


def _load_checklists() -> dict:
    """Load both checklists from JSON files."""
    checklists = {}

    for name, path in [
        ("0to1", CHECKLIST_0TO1_PATH),
        ("strategy", CHECKLIST_STRATEGY_PATH),
    ]:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                checklists[name] = data
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load {name} checklist: {e}")
        else:
            logger.warning(f"Checklist file not found: {path}")

    return checklists


def _select_relevant_items(
    checklists: dict,
    idea: dict,
    available_data: dict,
) -> list[dict]:
    """Select checklist items that can be evaluated given available data.

    Maps pipeline data availability to checklist categories:
    - Market research → 事業概要・戦略, 市場選定
    - Competitor data → 事業概要・戦略 (USP/差別化), 全体戦略
    - UE data → ファイナンス・計画, 価格設計, ユニットエコノミクス, 収益構造
    - Idea data → 事業概要・戦略, マーケティング, セールス
    """
    selected = []

    # Categories evaluable with market research + competitor + idea data
    always_categories = [
        "事業概要・戦略", "市場選定", "顧客理解", "全体戦略",
        "マーケティング", "セールス", "リスク・法務",
        "顧客開拓", "仕組み化",
    ]

    # Categories requiring UE data
    ue_categories = [
        "ファイナンス・計画", "価格設計", "収益構造",
        "ユニットエコノミクス", "資金計画",
    ]

    # Exit strategy always relevant
    exit_categories = ["出口戦略", "組織・採用"]

    has_ue = bool(available_data.get("unit_economics"))
    active_categories = always_categories + exit_categories
    if has_ue:
        active_categories += ue_categories

    for cl_name, cl_data in checklists.items():
        for category in cl_data.get("categories", []):
            cat_name = category.get("name", "")
            if cat_name in active_categories:
                for item in category.get("items", []):
                    selected.append({
                        "checklist": cl_name,
                        "category": cat_name,
                        "no": item.get("no"),
                        "question": item.get("question", ""),
                    })

    return selected


def evaluate(
    ideas: list[dict],
    market_data: list[dict] | None = None,
    competitor_data: list[dict] | None = None,
    ue_data: list[dict] | None = None,
    pain_data: list[dict] | None = None,
    ceo_profile: str = "",
) -> list[dict]:
    """Evaluate business ideas against checklist items.

    Args:
        ideas: Business ideas to evaluate.
        market_data: Market research results.
        competitor_data: Competitor analysis results.
        ue_data: Unit economics data.
        pain_data: Extracted pain points.
        ceo_profile: CEO profile text.

    Returns:
        List of evaluation results per idea: {
            idea_name, score (0-100), total_items, answered_items,
            answers: [{no, question, answer, confidence, status}],
            strengths, weaknesses, critical_gaps
        }
    """
    if not ideas:
        logger.warning("No ideas provided for checklist evaluation.")
        return []

    checklists = _load_checklists()
    if not checklists:
        logger.warning("No checklists loaded. Skipping evaluation.")
        return []

    available_data = {
        "market_research": market_data,
        "competitors": competitor_data,
        "unit_economics": ue_data,
        "pains": pain_data,
    }

    results = []

    for idea in ideas:
        idea_name = idea.get("name", "不明")
        logger.info(f"Evaluating checklist for: {idea_name}")

        relevant_items = _select_relevant_items(checklists, idea, available_data)
        if not relevant_items:
            logger.warning(f"No relevant checklist items for: {idea_name}")
            continue

        # Build context for AI evaluation
        context_parts = [f"## 事業案: {idea_name}\n{idea.get('description', '')}"]
        context_parts.append(f"ターゲット: {idea.get('target_audience', '')}")
        context_parts.append(f"差別化: {idea.get('differentiator', '')}")
        context_parts.append(f"市場規模: {idea.get('market_size', '')}")

        if market_data:
            context_parts.append("\n## 市場調査データ")
            for m in market_data[:5]:
                context_parts.append(
                    f"- {m.get('market_name', '')}: TAM={m.get('market_size_tam', '')}, "
                    f"痛み={str(m.get('customer_pain_points', ''))[:200]}"
                )

        if competitor_data:
            context_parts.append("\n## 競合データ")
            for c in competitor_data[:10]:
                context_parts.append(
                    f"- {c.get('competitor_name', '')}: "
                    f"価格={c.get('pricing_model', '')}, 強み={c.get('strengths', '')[:100]}"
                )

        if ue_data:
            context_parts.append("\n## ユニットエコノミクス")
            for ue in ue_data:
                if ue.get("idea_name") == idea_name:
                    context_parts.append(json.dumps(ue, ensure_ascii=False, indent=2))

        if pain_data:
            context_parts.append("\n## 痛みデータ")
            for p in pain_data[:10]:
                context_parts.append(f"- [{p.get('severity', '中')}] {p.get('pain', '')}")

        if ceo_profile:
            context_parts.append(f"\n## CEOプロフィール\n{ceo_profile}")

        business_context = "\n".join(context_parts)

        # --- Batch evaluation by category to avoid JSON truncation ---
        # Group items by category
        category_groups: dict[str, list] = {}
        for item in relevant_items:
            cat = item.get("category", "その他")
            category_groups.setdefault(cat, []).append(item)

        # Merge batches into ~25 items per batch
        BATCH_SIZE = 25
        batches: list[list[dict]] = []
        current_batch: list[dict] = []
        for cat_name, cat_items in category_groups.items():
            if len(current_batch) + len(cat_items) > BATCH_SIZE and current_batch:
                batches.append(current_batch)
                current_batch = []
            current_batch.extend(cat_items)
        if current_batch:
            batches.append(current_batch)

        all_answers: list[dict] = []
        all_strengths: list[str] = []
        all_weaknesses: list[str] = []
        all_gaps: list[str] = []
        score_sum = 0.0
        score_count = 0

        template = jinja_env.get_template("checklist_eval_prompt.j2")
        system_msg = (
            "あなたは事業計画の評価専門家です。"
            "提供されたデータに基づき、各チェック項目に対して"
            "客観的かつ具体的に回答してください。"
            "データ不足で回答できない項目は confidence=0 としてください。"
            "必ずJSON配列で出力してください。"
        )

        for batch_idx, batch_items in enumerate(batches):
            logger.info(
                f"  Batch {batch_idx + 1}/{len(batches)}: "
                f"{len(batch_items)} items"
            )

            items_text = ""
            for item in batch_items:
                items_text += f"- No.{item['no']} [{item['category']}] {item['question']}\n"

            prompt = template.render(
                idea_name=idea_name,
                business_context=business_context,
                checklist_items=items_text,
                total_items=len(batch_items),
            )

            def _validator(data):
                return validate_checklist_evaluation(data)

            try:
                result = generate_json_with_retry(
                    prompt=prompt,
                    system=system_msg,
                    max_tokens=16384,
                    temperature=0.3,
                    max_retries=2,
                    validator=_validator,
                )

                if isinstance(result, list) and len(result) > 0:
                    batch_result = result[0] if isinstance(result[0], dict) else {"answers": result}
                elif isinstance(result, dict):
                    batch_result = result
                else:
                    batch_result = {"answers": []}

                all_answers.extend(batch_result.get("answers", []))
                all_strengths.extend(batch_result.get("strengths", []))
                all_weaknesses.extend(batch_result.get("weaknesses", []))
                all_gaps.extend(batch_result.get("critical_gaps", []))

                batch_score = batch_result.get("score")
                if isinstance(batch_score, (int, float)):
                    score_sum += batch_score
                    score_count += 1

            except Exception as e:
                logger.warning(f"  Batch {batch_idx + 1} failed: {e}")

        # Merge batch results
        avg_score = round(score_sum / score_count, 1) if score_count > 0 else 0
        eval_result = {
            "idea_name": idea_name,
            "score": avg_score,
            "total_items": len(relevant_items),
            "answered_items": len([a for a in all_answers if a.get("status") == "answered"]),
            "answers": all_answers,
            "strengths": list(dict.fromkeys(all_strengths))[:5],
            "weaknesses": list(dict.fromkeys(all_weaknesses))[:5],
            "critical_gaps": list(dict.fromkeys(all_gaps))[:10],
        }

        results.append(eval_result)
        logger.info(
            f"Checklist evaluation for {idea_name}: "
            f"score={avg_score}, "
            f"items={len(all_answers)}/{len(relevant_items)}"
        )

    return results


def format_evaluation_summary(evaluations: list[dict]) -> str:
    """Format checklist evaluation results for notification."""
    if not evaluations:
        return "チェックリスト評価: データなし"

    lines = ["📝 *チェックリスト評価結果*\n"]
    for ev in evaluations:
        name = ev.get("idea_name", "不明")
        score = ev.get("score", "N/A")
        answers = ev.get("answers", [])
        strengths = ev.get("strengths", [])
        gaps = ev.get("critical_gaps", [])

        health = "🟢" if isinstance(score, (int, float)) and score >= 70 else "🟡" if isinstance(score, (int, float)) and score >= 40 else "🔴"

        lines.append(f"{health} *{name}* — スコア: {score}/100 ({len(answers)}項目回答)")

        if strengths and isinstance(strengths, list):
            lines.append(f"  強み: {', '.join(str(s) for s in strengths[:3])}")
        if gaps and isinstance(gaps, list):
            lines.append(f"  要注意: {', '.join(str(g) for g in gaps[:3])}")

    return "\n".join(lines)
