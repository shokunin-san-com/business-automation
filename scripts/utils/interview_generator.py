"""
Interview script generator — creates 30-minute customer validation scripts.

Based on persona + pain hypotheses, generates structured interview scripts
with 5-stage validation questions, icebreakers, and closing.
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TEMPLATES_DIR, DATA_DIR, get_logger
from utils.claude_client import generate_text

logger = get_logger(__name__)
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

INTERVIEWS_DIR = DATA_DIR / "interviews"
INTERVIEWS_DIR.mkdir(parents=True, exist_ok=True)


def generate(
    ideas: list[dict],
    pain_data: list[dict] | None = None,
    ue_data: list[dict] | None = None,
    market_data: list[dict] | None = None,
) -> list[dict]:
    """Generate interview scripts for top business ideas.

    Args:
        ideas: Business ideas to generate scripts for.
        pain_data: Extracted pain points for hypothesis formation.
        ue_data: Unit economics data for pricing validation questions.
        market_data: Market research for industry context.

    Returns:
        List of {idea_name, script_markdown, file_path} dicts.
    """
    if not ideas:
        logger.warning("No ideas provided for interview generation.")
        return []

    results = []

    for idea in ideas:
        idea_name = idea.get("name", "不明")
        logger.info(f"Generating interview script for: {idea_name}")

        # Build pain context for this idea's market
        pain_context = ""
        if pain_data:
            related_pains = [
                p for p in pain_data
                if p.get("related_market", "") in idea.get("category", "")
                or p.get("related_market", "") in idea.get("name", "")
            ]
            if not related_pains:
                related_pains = pain_data[:10]  # Use first 10 if no match

            for p in related_pains:
                pain_context += (
                    f"\n- [{p['severity']}] {p['pain']} "
                    f"(影響: {p.get('who_affected', 'N/A')})"
                )

        # Build UE context
        ue_context = ""
        if ue_data:
            for ue in ue_data:
                if ue.get("idea_name", "") == idea_name:
                    ue_context = (
                        f"想定価格モデル: {ue.get('pricing_model', 'N/A')}\n"
                        f"LTV: {ue.get('ltv', 'N/A')} / CAC: {ue.get('cac', 'N/A')}\n"
                        f"BEP: {ue.get('bep_months', 'N/A')}ヶ月"
                    )
                    break

        template = jinja_env.get_template("interview_script_prompt.j2")
        prompt = template.render(
            idea_name=idea_name,
            idea_description=idea.get("description", ""),
            target_audience=idea.get("target_audience", ""),
            differentiator=idea.get("differentiator", ""),
            pain_context=pain_context,
            ue_context=ue_context,
        )

        script_md = generate_text(
            prompt=prompt,
            system=(
                "あなたは顧客開発（Customer Development）の専門家です。"
                "リーン・スタートアップの手法に基づき、"
                "仮説検証のためのインタビュースクリプトを作成してください。"
                "Markdown形式で出力してください。"
            ),
            max_tokens=4096,
            temperature=0.5,
        )

        # Save to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        safe_name = idea_name[:30].replace(" ", "_").replace("/", "_")
        filename = f"interview_{safe_name}_{timestamp}.md"
        file_path = INTERVIEWS_DIR / filename

        file_path.write_text(script_md, encoding="utf-8")
        logger.info(f"Saved interview script: {file_path}")

        results.append({
            "idea_name": idea_name,
            "script_markdown": script_md,
            "file_path": str(file_path),
        })

    return results


def format_interview_summary(scripts: list[dict]) -> str:
    """Format interview generation results for notification."""
    if not scripts:
        return "インタビュースクリプト: 生成なし"

    lines = ["📋 *インタビュースクリプト生成完了*\n"]
    for s in scripts:
        lines.append(f"  - {s['idea_name']}: {s['file_path']}")

    return "\n".join(lines)
