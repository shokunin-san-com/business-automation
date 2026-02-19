"""
exploration_context.py — Build context from upstream exploration pipeline.

Reads market_selection (selected) and competitor_analysis sheets,
formats them as text for injection into idea generation prompts.
"""
from __future__ import annotations

import json
from .sheets_client import get_all_rows


def get_exploration_context() -> str:
    """Build text context from exploration pipeline data."""
    parts = []

    # Selected markets
    try:
        selections = get_all_rows("market_selection")
        selected = [s for s in selections if s.get("status") == "selected"]
        if selected:
            parts.append("## 選定済み市場")
            for s in selected:
                parts.append(
                    f"### {s.get('market_name', '')}"
                    f"\n- スコア: {s.get('total_score', '')}/50"
                    f"\n- 推奨参入角度: {s.get('recommended_entry_angle', '')}"
                    f"\n- 根拠: {s.get('rationale', '')}"
                )
    except Exception:
        pass

    # Competitor gaps
    try:
        competitors = get_all_rows("competitor_analysis")
        if competitors:
            gap_map: dict[str, list] = {}
            for c in competitors:
                market = c.get("market_name", "")
                gaps_raw = c.get("gap_opportunities", "[]")
                try:
                    gaps = json.loads(gaps_raw) if isinstance(gaps_raw, str) else gaps_raw
                except (json.JSONDecodeError, TypeError):
                    gaps = []
                if not isinstance(gaps, list):
                    gaps = [str(gaps)]
                if market not in gap_map:
                    gap_map[market] = []
                gap_map[market].extend(gaps)

            if gap_map:
                parts.append("\n## 競合ギャップ・参入機会")
                for market, gaps in gap_map.items():
                    parts.append(f"### {market}")
                    for gap in gaps[:5]:
                        parts.append(f"- {gap}")
    except Exception:
        pass

    return "\n".join(parts) if parts else ""
