"""
Pain extraction module — extracts customer/market pains from knowledge base.

Reads knowledge_base sheet (PDF summaries + chapters), uses AI to identify
structured pain points with severity classification and source traceability.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TEMPLATES_DIR, get_logger
from utils.claude_client import generate_json_with_retry
from utils.sheets_client import get_all_rows

logger = get_logger(__name__)
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


def _load_knowledge_entries() -> list[dict]:
    """Load knowledge base entries with chapter data."""
    try:
        rows = get_all_rows("knowledge_base")
        entries = []
        for r in rows:
            chapters_raw = r.get("chapters_json", "")
            chapters = []
            if chapters_raw:
                try:
                    chapters = json.loads(chapters_raw)
                except (json.JSONDecodeError, TypeError):
                    pass
            entries.append({
                "title": r.get("title", r.get("filename", "")),
                "summary": r.get("summary", ""),
                "chapters": chapters,
            })
        return entries
    except Exception as e:
        logger.warning(f"Failed to load knowledge base: {e}")
        return []


def extract_pains(
    market_names: list[str],
    market_research_data: list[dict] | None = None,
) -> list[dict]:
    """Extract pain points from knowledge base for given markets.

    Args:
        market_names: List of market names to focus pain extraction on.
        market_research_data: Optional market research results for context.

    Returns:
        List of pain dicts: {
            pain, severity (高/中/低), source_title, chapter,
            who_affected, process_affected, related_market
        }
    """
    knowledge_entries = _load_knowledge_entries()
    if not knowledge_entries:
        logger.warning("No knowledge base entries found. Skipping pain extraction.")
        return []

    # Build knowledge context string
    knowledge_text = ""
    for entry in knowledge_entries:
        knowledge_text += f"\n### {entry['title']}\n{entry['summary']}\n"
        for ch in entry.get("chapters", []):
            if isinstance(ch, dict):
                ch_title = ch.get("title", ch.get("chapter", ""))
                ch_summary = ch.get("summary", "")
                if ch_title:
                    knowledge_text += f"  - {ch_title}: {ch_summary}\n"

    # Build market context
    market_context = ""
    if market_research_data:
        for mr in market_research_data:
            market_context += (
                f"\n- {mr.get('market_name', '')}: "
                f"痛み={mr.get('customer_pain_points', 'N/A')}, "
                f"構造={mr.get('industry_structure', 'N/A')}"
            )

    template = jinja_env.get_template("pain_extraction_prompt.j2")
    prompt = template.render(
        markets=", ".join(market_names),
        knowledge_text=knowledge_text,
        market_context=market_context,
    )

    result = generate_json_with_retry(
        prompt=prompt,
        system=(
            "あなたは事業開発の痛み分析専門家です。"
            "ナレッジベースの情報から、市場の具体的な痛みを抽出してください。"
            "各痛みにはソース（書籍名・章）を必ず付与してください。"
            "必ずJSON配列で出力してください。"
        ),
        max_tokens=8192,
        temperature=0.4,
        max_retries=2,
    )

    if isinstance(result, dict):
        result = [result]

    # Ensure each pain has required fields
    cleaned = []
    for p in result:
        if isinstance(p, dict) and p.get("pain"):
            cleaned.append({
                "pain": p.get("pain", ""),
                "severity": p.get("severity", "中"),
                "source_title": p.get("source_title", "不明"),
                "chapter": p.get("chapter", ""),
                "who_affected": p.get("who_affected", ""),
                "process_affected": p.get("process_affected", ""),
                "related_market": p.get("related_market", ""),
            })

    logger.info(f"Extracted {len(cleaned)} pain points from knowledge base")
    return cleaned


def format_pains_for_scoring(pains: list[dict]) -> str:
    """Format pain data as text context for market selection scoring."""
    if not pains:
        return ""

    lines = ["## ナレッジベースから抽出した痛み（ソース付き）\n"]
    for p in pains:
        severity_emoji = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(p["severity"], "⚪")
        lines.append(
            f"{severity_emoji} [{p['severity']}] {p['pain']}\n"
            f"   影響者: {p['who_affected']} | プロセス: {p['process_affected']}\n"
            f"   出典: {p['source_title']} {p['chapter']}\n"
            f"   関連市場: {p['related_market']}"
        )

    return "\n".join(lines)
