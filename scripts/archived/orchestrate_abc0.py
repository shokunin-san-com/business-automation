"""
orchestrate_abc0.py — Autonomous ABC0 pipeline orchestrator.

Runs the full pipeline: A(Market Research) → P(Pain Extraction) →
B(Market Selection + Auto-Approve) → C(Competitor Analysis) →
0(Idea Generation) → U(Unit Economics) → E(Checklist Evaluation) →
I(Interview Script) → Self-Reflection.

Includes validation, retry, auto-approval, and self-reflection.

Usage:
    SCRIPT_NAME=orchestrate_abc0 python run.py
    python scripts/orchestrate_abc0.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import TEMPLATES_DIR, get_logger
from utils.claude_client import generate_json, generate_json_with_retry
from utils.sheets_client import (
    get_all_rows,
    append_rows,
    find_row_index,
    update_cell,
    get_worksheet,
    ensure_sheet_exists,
    get_sheet_urls,
)
from utils.slack_notifier import send_message as notify
from utils.status_writer import update_status
from utils.pdf_knowledge import get_knowledge_summary
from utils.validators import (
    validate_market_research,
    validate_market_selection,
    validate_competitor_analysis,
    validate_idea_output,
)
from utils.pain_extractor import extract_pains, format_pains_for_scoring
from utils.unit_economics import calculate as calculate_ue, format_ue_summary
from utils.interview_generator import generate as generate_interviews, format_interview_summary
from utils.checklist_evaluator import evaluate as evaluate_checklist, format_evaluation_summary

# Import existing step functions
from A_market_research import research_market, save_research_to_sheets
from B_market_selection import score_markets, save_selections_to_sheets
from C_competitor_analysis import (
    analyze_competitors,
    save_analysis_to_sheets as save_competitors_to_sheets,
    _get_market_research,
)

logger = get_logger("orchestrate_abc0", "orchestrate_abc0.log")
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

# Step result tracking
STEP_OK = "✅ 成功"
STEP_WARN = "⚠️ 警告あり"
STEP_FAIL = "❌ 失敗"
STEP_SKIP = "⏭️ スキップ"


def _load_settings() -> dict:
    rows = get_all_rows("settings")
    return {r["key"]: r["value"] for r in rows}


def _get_existing_research_ids() -> set:
    try:
        rows = get_all_rows("market_research")
        return {r.get("id", "") for r in rows}
    except Exception:
        return set()


def _get_unscored_research() -> list:
    research_rows = get_all_rows("market_research")
    try:
        selection_rows = get_all_rows("market_selection")
        scored_ids = {r.get("market_research_id", "") for r in selection_rows}
    except Exception:
        scored_ids = set()
    return [
        r for r in research_rows
        if r.get("id") and r["id"] not in scored_ids and r.get("status") != "archived"
    ]


def _get_selected_markets() -> list:
    try:
        rows = get_all_rows("market_selection")
        return [r for r in rows if r.get("status") == "selected"]
    except Exception:
        return []


def _already_analyzed(market_selection_id: str) -> bool:
    try:
        rows = get_all_rows("competitor_analysis")
        return any(r.get("market_selection_id") == market_selection_id for r in rows)
    except Exception:
        return False


# =========================================================================
# Step A: Market Research (+ sublayer decomposition)
# =========================================================================
def step_a_market_research(settings: dict, knowledge_context: str) -> dict:
    """Run market research for all configured markets."""
    logger.info("=" * 60)
    logger.info("Step A: 市場調査開始")
    update_status("orchestrate_abc0", "running", "Step A: 市場調査中...")

    markets_str = settings.get(
        "exploration_markets",
        settings.get("target_industries", "IT,エネルギー"),
    )
    markets = [m.strip() for m in markets_str.split(",") if m.strip()]
    market_direction_notes = settings.get("market_direction_notes", "")
    batch_id = datetime.now().strftime("%Y-%m-%d")
    existing_ids = _get_existing_research_ids()

    all_research = []
    errors = []
    warnings = []

    for market in markets:
        import re
        slug = re.sub(r"[^\w\s-]", "", market.lower().strip())
        slug = re.sub(r"[\s]+", "-", slug).strip("-")
        if not slug:
            slug = f"market-{abs(hash(market)) % 100000:05d}"

        if any(eid.startswith(slug) or eid == slug for eid in existing_ids):
            logger.info(f"既調査スキップ: {market}")
            continue

        try:
            segments = research_market(market, settings, knowledge_context, market_direction_notes)

            # Validate
            expected = int(settings.get("exploration_segments_per_market", "3"))
            vr = validate_market_research(segments, expected)
            warnings.extend(vr.warnings)
            if not vr.valid:
                errors.extend(vr.errors)
                logger.warning(f"Validation errors for {market}: {vr.errors}")

            all_research.extend(vr.data or segments)
        except Exception as e:
            errors.append(f"{market}: {str(e)}")
            logger.error(f"Market research failed for {market}: {e}")

    count = 0
    if all_research:
        count = save_research_to_sheets(all_research, batch_id)

    status = STEP_FAIL if not all_research else (STEP_WARN if errors else STEP_OK)
    return {
        "name": "Step A: 市場調査",
        "status": status,
        "count": count,
        "errors": errors,
        "warnings": warnings,
        "data": all_research,
        "markets": markets,
    }


# =========================================================================
# Step P: Pain Extraction
# =========================================================================
def step_p_pain_extraction(market_names: list, market_data: list) -> dict:
    """Extract pains from knowledge base."""
    logger.info("=" * 60)
    logger.info("Step P: 痛み抽出開始")
    update_status("orchestrate_abc0", "running", "Step P: 痛み抽出中...")

    try:
        pains = extract_pains(market_names, market_data)
        status = STEP_OK if pains else STEP_WARN
        return {
            "name": "Step P: 痛み抽出",
            "status": status,
            "count": len(pains),
            "errors": [],
            "warnings": [] if pains else ["ナレッジベースから痛みを抽出できませんでした"],
            "data": pains,
        }
    except Exception as e:
        logger.error(f"Pain extraction failed: {e}")
        return {
            "name": "Step P: 痛み抽出",
            "status": STEP_FAIL,
            "count": 0,
            "errors": [str(e)],
            "warnings": [],
            "data": [],
        }


# =========================================================================
# Step B: Market Selection (with pain context)
# =========================================================================
def step_b_market_selection(
    settings: dict,
    knowledge_context: str,
    pain_context: str,
) -> dict:
    """Score and rank markets."""
    logger.info("=" * 60)
    logger.info("Step B: 市場選定開始")
    update_status("orchestrate_abc0", "running", "Step B: 市場選定中...")

    errors = []
    warnings = []

    try:
        unscored = _get_unscored_research()
        if not unscored:
            return {
                "name": "Step B: 市場選定",
                "status": STEP_SKIP,
                "count": 0,
                "errors": [],
                "warnings": ["スコアリング対象の市場がありません"],
                "data": [],
            }

        market_direction_notes = settings.get("market_direction_notes", "")
        # Inject pain context into direction notes
        if pain_context:
            market_direction_notes = (
                f"{market_direction_notes}\n\n{pain_context}"
                if market_direction_notes
                else pain_context
            )

        selections = score_markets(
            unscored, settings, knowledge_context, market_direction_notes
        )

        # Validate
        weights_str = settings.get(
            "exploration_scoring_weights",
            '{"distortion":3,"barrier":2,"bpo":2,"growth":1.5,"capability":1.5}',
        )
        weights = json.loads(weights_str)
        vr = validate_market_selection(selections, weights)
        warnings.extend(vr.warnings)
        if not vr.valid:
            errors.extend(vr.errors)

        selections = vr.data or selections
        selections.sort(key=lambda x: float(x.get("total_score", 0)), reverse=True)

        top_n = int(settings.get("selection_top_n", "3"))
        batch_id = datetime.now().strftime("%Y-%m-%d")
        count = save_selections_to_sheets(selections, batch_id, top_n=top_n)

        status = STEP_FAIL if not selections else (STEP_WARN if errors else STEP_OK)
        return {
            "name": "Step B: 市場選定",
            "status": status,
            "count": count,
            "errors": errors,
            "warnings": warnings,
            "data": selections,
        }
    except Exception as e:
        logger.error(f"Market selection failed: {e}")
        return {
            "name": "Step B: 市場選定",
            "status": STEP_FAIL,
            "count": 0,
            "errors": [str(e)],
            "warnings": [],
            "data": [],
        }


# =========================================================================
# Auto-Approve: Promote top markets to "selected"
# =========================================================================
def step_auto_approve(settings: dict, selections: list) -> dict:
    """Auto-approve top N markets."""
    logger.info("=" * 60)
    logger.info("自動承認開始")
    update_status("orchestrate_abc0", "running", "自動承認中...")

    auto_approve = settings.get("orchestrator_auto_approve", "true").lower() == "true"
    if not auto_approve:
        return {
            "name": "自動承認",
            "status": STEP_SKIP,
            "count": 0,
            "errors": [],
            "warnings": ["orchestrator_auto_approve=false のためスキップ"],
            "data": [],
        }

    top_n_str = settings.get("orchestrator_auto_approve_n", "")
    top_n = int(top_n_str) if top_n_str else int(settings.get("selection_top_n", "3"))
    min_score = float(settings.get("orchestrator_min_score_threshold", "0"))

    approved = []
    errors = []

    try:
        ws = get_worksheet("market_selection")
        headers = ws.row_values(1)
        col_map = {h: i + 1 for i, h in enumerate(headers)}
        status_col = col_map.get("status")
        reviewed_col = col_map.get("reviewed_by")

        if not status_col:
            return {
                "name": "自動承認",
                "status": STEP_FAIL,
                "count": 0,
                "errors": ["status カラムが見つかりません"],
                "warnings": [],
                "data": [],
            }

        for sel in selections[:top_n]:
            total_score = float(sel.get("total_score", 0))
            if total_score < min_score:
                logger.info(
                    f"スコア {total_score} < 閾値 {min_score}: "
                    f"{sel.get('market_name', '')} スキップ"
                )
                continue

            market_research_id = sel.get("market_research_id", "")
            row_idx = find_row_index("market_selection", "market_research_id", market_research_id)

            if row_idx:
                update_cell("market_selection", row_idx, status_col, "selected")
                if reviewed_col:
                    update_cell("market_selection", row_idx, reviewed_col, "autonomous_agent")
                approved.append(sel)
                logger.info(f"自動承認: {sel.get('market_name', '')} (score={total_score})")
                time.sleep(1)  # Rate limit
            else:
                errors.append(f"行が見つかりません: {market_research_id}")

    except Exception as e:
        errors.append(str(e))
        logger.error(f"Auto-approve failed: {e}")

    status = STEP_FAIL if errors and not approved else (STEP_WARN if errors else STEP_OK)
    return {
        "name": "自動承認",
        "status": status,
        "count": len(approved),
        "errors": errors,
        "warnings": [],
        "data": approved,
    }


# =========================================================================
# Step C: Competitor Analysis
# =========================================================================
def step_c_competitor_analysis(settings: dict, knowledge_context: str) -> dict:
    """Analyze competitors for selected markets."""
    logger.info("=" * 60)
    logger.info("Step C: 競合調査開始")
    update_status("orchestrate_abc0", "running", "Step C: 競合調査中...")

    errors = []
    warnings = []
    all_competitors = []

    try:
        selected_markets = _get_selected_markets()
        if not selected_markets:
            return {
                "name": "Step C: 競合調査",
                "status": STEP_SKIP,
                "count": 0,
                "errors": [],
                "warnings": ["承認済み市場がありません"],
                "data": [],
            }

        for market in selected_markets:
            sel_id = market.get("id", "")
            if _already_analyzed(sel_id):
                logger.info(f"既分析スキップ: {market.get('market_name')}")
                continue

            market_name = market.get("market_name", "")
            logger.info(f"競合分析中: {market_name}")

            try:
                research = _get_market_research(market.get("market_research_id", ""))
                competitors = analyze_competitors(market, research, settings, knowledge_context)

                vr = validate_competitor_analysis(
                    competitors,
                    int(settings.get("competitors_per_market", "5")),
                )
                warnings.extend(vr.warnings)
                if not vr.valid:
                    errors.extend(vr.errors)

                competitor_data = vr.data or competitors
                count = save_competitors_to_sheets(competitor_data, sel_id, market_name)
                all_competitors.extend(competitor_data)
                logger.info(f"{market_name}: {count}社分析完了")
            except Exception as e:
                errors.append(f"{market_name}: {str(e)}")
                logger.error(f"Competitor analysis failed for {market_name}: {e}")

    except Exception as e:
        errors.append(str(e))

    status = STEP_FAIL if not all_competitors and errors else (STEP_WARN if errors else STEP_OK)
    return {
        "name": "Step C: 競合調査",
        "status": status,
        "count": len(all_competitors),
        "errors": errors,
        "warnings": warnings,
        "data": all_competitors,
    }


# =========================================================================
# Step 0: Idea Generation
# =========================================================================
def step_0_idea_generation(settings: dict, knowledge_context: str) -> dict:
    """Generate business ideas using all available context."""
    logger.info("=" * 60)
    logger.info("Step 0: 事業案生成開始")
    update_status("orchestrate_abc0", "running", "Step 0: 事業案生成中...")

    try:
        from utils.exploration_context import get_exploration_context
        from utils.learning_engine import get_learning_context
        from utils.ceo_profile import get_ceo_profile_context

        exploration_context = get_exploration_context()
        learning_context = get_learning_context(categories=["idea_generation"])
        ceo_profile_context = get_ceo_profile_context()
        idea_direction_notes = settings.get("idea_direction_notes", "")
        num_ideas = int(settings.get("ideas_per_run", "3"))

        template = jinja_env.get_template("idea_gen_prompt.j2")
        prompt = template.render(
            target_industries=settings.get("target_industries", "IT,エネルギー"),
            trend_keywords=settings.get("trend_keywords", "AI,DX"),
            num_ideas=num_ideas,
            knowledge_context=knowledge_context,
            exploration_context=exploration_context,
            learning_context=learning_context,
            ceo_profile_context=ceo_profile_context,
            idea_direction_notes=idea_direction_notes,
        )

        use_ceo = settings.get("use_ceo_profile", "false").lower() == "true"

        def _validator(data):
            return validate_idea_output(data, num_ideas, check_ceo_fit=use_ceo)

        ideas = generate_json_with_retry(
            prompt=prompt,
            system="あなたは日本市場に精通した事業戦略コンサルタントです。",
            max_tokens=8192,
            temperature=0.8,
            max_retries=2,
            validator=_validator,
        )

        if isinstance(ideas, dict):
            ideas = [ideas]

        # Save to sheets
        from datetime import datetime as dt
        import re as _re
        now = dt.now().strftime("%Y-%m-%d %H:%M")
        rows = []
        for idea in ideas:
            name = idea.get("name", "unknown")
            slug = _re.sub(r"[^\w\s-]", "", name.lower().strip())
            slug = _re.sub(r"[\s]+", "-", slug).strip("-") or f"idea-{abs(hash(name)) % 100000:05d}"
            rows.append([
                slug, name,
                idea.get("category", ""), idea.get("description", ""),
                idea.get("target_audience", ""), "draft", "", "auto",
                idea.get("market_size", ""), idea.get("differentiator", ""),
                now, idea.get("ceo_fit_score", ""), idea.get("ceo_fit_reason", ""),
            ])

        if rows:
            append_rows("business_ideas", rows)

        return {
            "name": "Step 0: 事業案生成",
            "status": STEP_OK if ideas else STEP_FAIL,
            "count": len(ideas),
            "errors": [] if ideas else ["事業案を生成できませんでした"],
            "warnings": [],
            "data": ideas,
        }
    except Exception as e:
        logger.error(f"Idea generation failed: {e}")
        return {
            "name": "Step 0: 事業案生成",
            "status": STEP_FAIL,
            "count": 0,
            "errors": [str(e)],
            "warnings": [],
            "data": [],
        }


# =========================================================================
# Step U: Unit Economics
# =========================================================================
def step_u_unit_economics(
    ideas: list,
    market_data: list,
    competitor_data: list,
    ceo_profile: str,
) -> dict:
    """Calculate unit economics for each idea."""
    logger.info("=" * 60)
    logger.info("Step U: ユニットエコノミクス算出開始")
    update_status("orchestrate_abc0", "running", "Step U: UE算出中...")

    try:
        ue_results = calculate_ue(ideas, market_data, competitor_data, ceo_profile)

        # Save to business_ideas sheet (update unit_economics_json column)
        if ue_results:
            _update_ideas_with_ue(ue_results)

        return {
            "name": "Step U: ユニットエコノミクス",
            "status": STEP_OK if ue_results else STEP_WARN,
            "count": len(ue_results),
            "errors": [],
            "warnings": [] if ue_results else ["UEを算出できませんでした"],
            "data": ue_results,
        }
    except Exception as e:
        logger.error(f"Unit economics failed: {e}")
        return {
            "name": "Step U: ユニットエコノミクス",
            "status": STEP_FAIL,
            "count": 0,
            "errors": [str(e)],
            "warnings": [],
            "data": [],
        }


def _update_ideas_with_ue(ue_results: list):
    """Update business_ideas sheet with unit_economics_json."""
    try:
        # Ensure column exists
        ws = get_worksheet("business_ideas")
        headers = ws.row_values(1)
        if "unit_economics_json" not in headers:
            ws.update_cell(1, len(headers) + 1, "unit_economics_json")
            headers.append("unit_economics_json")

        ue_col = headers.index("unit_economics_json") + 1

        for ue in ue_results:
            idea_name = ue.get("idea_name", "")
            if not idea_name:
                continue
            row_idx = find_row_index("business_ideas", "name", idea_name)
            if row_idx:
                update_cell(
                    "business_ideas", row_idx, ue_col,
                    json.dumps(ue, ensure_ascii=False),
                )
                time.sleep(0.5)
    except Exception as e:
        logger.warning(f"Failed to update UE in sheets: {e}")


# =========================================================================
# Step E: Checklist Evaluation
# =========================================================================
def step_e_checklist_evaluation(
    ideas: list,
    market_data: list,
    competitor_data: list,
    ue_data: list,
    pain_data: list,
    ceo_profile: str,
) -> dict:
    """Evaluate ideas against checklists."""
    logger.info("=" * 60)
    logger.info("Step E: チェックリスト評価開始")
    update_status("orchestrate_abc0", "running", "Step E: チェックリスト評価中...")

    try:
        evaluations = evaluate_checklist(
            ideas, market_data, competitor_data, ue_data, pain_data, ceo_profile
        )

        # Save to sheets
        if evaluations:
            _update_ideas_with_checklist(evaluations)

        return {
            "name": "Step E: チェックリスト評価",
            "status": STEP_OK if evaluations else STEP_WARN,
            "count": len(evaluations),
            "errors": [],
            "warnings": [] if evaluations else ["チェックリスト評価できませんでした"],
            "data": evaluations,
        }
    except Exception as e:
        logger.error(f"Checklist evaluation failed: {e}")
        return {
            "name": "Step E: チェックリスト評価",
            "status": STEP_FAIL,
            "count": 0,
            "errors": [str(e)],
            "warnings": [],
            "data": [],
        }


def _update_ideas_with_checklist(evaluations: list):
    """Update business_ideas sheet with checklist_json."""
    try:
        ws = get_worksheet("business_ideas")
        headers = ws.row_values(1)
        if "checklist_json" not in headers:
            ws.update_cell(1, len(headers) + 1, "checklist_json")
            headers.append("checklist_json")

        cl_col = headers.index("checklist_json") + 1

        for ev in evaluations:
            idea_name = ev.get("idea_name", "")
            if not idea_name:
                continue
            row_idx = find_row_index("business_ideas", "name", idea_name)
            if row_idx:
                update_cell(
                    "business_ideas", row_idx, cl_col,
                    json.dumps(ev, ensure_ascii=False),
                )
                time.sleep(0.5)
    except Exception as e:
        logger.warning(f"Failed to update checklist in sheets: {e}")


# =========================================================================
# Step I: Interview Script Generation
# =========================================================================
def step_i_interview_scripts(
    ideas: list,
    pain_data: list,
    ue_data: list,
    market_data: list,
) -> dict:
    """Generate interview scripts for top ideas."""
    logger.info("=" * 60)
    logger.info("Step I: インタビュースクリプト生成開始")
    update_status("orchestrate_abc0", "running", "Step I: インタビュー生成中...")

    try:
        scripts = generate_interviews(ideas, pain_data, ue_data, market_data)
        return {
            "name": "Step I: インタビュースクリプト",
            "status": STEP_OK if scripts else STEP_WARN,
            "count": len(scripts),
            "errors": [],
            "warnings": [] if scripts else ["インタビュースクリプトを生成できませんでした"],
            "data": scripts,
        }
    except Exception as e:
        logger.error(f"Interview generation failed: {e}")
        return {
            "name": "Step I: インタビュースクリプト",
            "status": STEP_FAIL,
            "count": 0,
            "errors": [str(e)],
            "warnings": [],
            "data": [],
        }


# =========================================================================
# Self-Reflection
# =========================================================================
def step_reflection(
    steps: list[dict],
    settings: dict,
    auto_approved: list,
    ideas: list,
    ue_data: list,
    checklist_data: list,
    total_duration: str,
) -> dict:
    """AI self-reflection on pipeline results."""
    logger.info("=" * 60)
    logger.info("自己反省開始")
    update_status("orchestrate_abc0", "running", "自己反省中...")

    try:
        template = jinja_env.get_template("pipeline_reflection_prompt.j2")
        prompt = template.render(
            execution_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
            total_duration=total_duration,
            steps=steps,
            auto_approved_markets=auto_approved,
            ideas_generated=ideas,
            ue_summary=format_ue_summary(ue_data) if ue_data else "",
            checklist_summary=format_evaluation_summary(checklist_data) if checklist_data else "",
            current_direction_notes=settings.get("market_direction_notes", ""),
            previous_improvement_log=settings.get("pipeline_improvement_log", ""),
        )

        reflection = generate_json(
            prompt=prompt,
            system="あなたはABC0パイプラインの自己反省エンジンです。客観的に評価してください。",
            max_tokens=4096,
            temperature=0.4,
        )

        if isinstance(reflection, list) and len(reflection) > 0:
            reflection = reflection[0]

        # Update direction_notes with reflection (append, don't overwrite)
        if isinstance(reflection, dict):
            _append_direction_notes(reflection, settings)

        return reflection if isinstance(reflection, dict) else {"summary": "反省結果の解析に失敗"}
    except Exception as e:
        logger.error(f"Reflection failed: {e}")
        return {"summary": f"反省エラー: {str(e)}"}


def _append_direction_notes(reflection: dict, settings: dict):
    """Append reflection insights to direction_notes (prepend, don't overwrite)."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # --- 1. direction_notes の更新 ---
    for notes_key, update_key in [
        ("market_direction_notes", "market_direction_update"),
        ("idea_direction_notes", "idea_direction_update"),
    ]:
        update_text = reflection.get(update_key, "")
        if not update_text:
            continue

        current = settings.get(notes_key, "")
        new_entry = f"[{timestamp} autonomous_agent] {update_text}"
        updated = f"{new_entry}\n{current}" if current else new_entry

        try:
            row_idx = find_row_index("settings", "key", notes_key)
            if row_idx:
                update_cell("settings", row_idx, 2, updated)  # col 2 = value
                logger.info(f"Updated {notes_key} with reflection")
        except Exception as e:
            logger.warning(f"Failed to update {notes_key}: {e}")

    # --- 2. improvement_suggestions の蓄積 ---
    suggestions = reflection.get("improvement_suggestions", [])
    risks = reflection.get("risks_identified", [])
    next_actions = reflection.get("next_actions", [])

    if suggestions or risks or next_actions:
        parts = []
        if suggestions:
            parts.append("改善: " + " / ".join(str(s) for s in suggestions[:5]))
        if risks:
            parts.append("リスク: " + " / ".join(str(r) for r in risks[:3]))
        if next_actions:
            parts.append("次回: " + " / ".join(str(a) for a in next_actions[:3]))

        new_log = f"[{timestamp}] " + " | ".join(parts)

        current_log = settings.get("pipeline_improvement_log", "")
        # 最新5件分だけ保持（古いものは切り捨て）
        existing_entries = [e.strip() for e in current_log.split("\n") if e.strip()]
        existing_entries.insert(0, new_log)
        updated_log = "\n".join(existing_entries[:5])

        try:
            row_idx = find_row_index("settings", "key", "pipeline_improvement_log")
            if row_idx:
                update_cell("settings", row_idx, 2, updated_log)
                logger.info(f"Updated pipeline_improvement_log ({len(suggestions)} suggestions, {len(risks)} risks, {len(next_actions)} actions)")
            else:
                # キーが存在しない場合は追加
                append_rows("settings", [["pipeline_improvement_log", updated_log, "自己反省の改善提案・リスク・次回アクション蓄積"]])
                logger.info("Created pipeline_improvement_log setting")
        except Exception as e:
            logger.warning(f"Failed to update pipeline_improvement_log: {e}")


# =========================================================================
# Notification
# =========================================================================
# Step name → relevant sheet names mapping
STEP_SHEET_MAP: dict[str, list[str]] = {
    "Step A": ["market_research"],
    "Step P": ["knowledge_base"],
    "Step B": ["market_selection"],
    "自動承認": ["market_selection"],
    "Step C": ["competitor_analysis"],
    "Step 0": ["business_ideas"],
    "Step U": ["business_ideas"],
    "Step E": ["business_ideas"],
    "Step I": [],  # interview scripts are saved as files, not sheets
}


def send_pipeline_report(
    steps: list[dict],
    auto_approved: list,
    reflection: dict,
    total_duration: str,
):
    """Send summary notification to Slack/Google Chat."""

    # Collect all relevant sheet names from steps, then fetch URLs in one call
    all_sheet_names = set()
    for step in steps:
        step_key = step["name"].split(":")[0]
        for sheet_name in STEP_SHEET_MAP.get(step_key, []):
            all_sheet_names.add(sheet_name)
    # Always include settings for direction_notes link
    all_sheet_names.add("settings")

    try:
        sheet_urls = get_sheet_urls(list(all_sheet_names))
    except Exception as e:
        logger.warning(f"Failed to get sheet URLs: {e}")
        sheet_urls = {}

    lines = [
        "🤖 *ABC0 自律型パイプライン完了レポート*",
        f"⏱️ 所要時間: {total_duration}",
        "",
        "*ステップ結果:*",
    ]

    for step in steps:
        count_str = f" ({step.get('count', 0)}件)" if step.get("count") else ""
        step_key = step["name"].split(":")[0]
        # Build sheet link(s) for this step
        relevant_sheets = STEP_SHEET_MAP.get(step_key, [])
        link_parts = []
        for sn in relevant_sheets:
            url = sheet_urls.get(sn, "")
            if url:
                link_parts.append(f"<{url}|📊{sn}>")
        link_str = f"  → {' '.join(link_parts)}" if link_parts else ""
        lines.append(f"  {step['status']} {step['name']}{count_str}{link_str}")

    if auto_approved:
        ms_url = sheet_urls.get("market_selection", "")
        ms_link = f" <{ms_url}|📊シートを開く>" if ms_url else ""
        lines.append(f"\n*自動承認市場:*{ms_link}")
        for m in auto_approved:
            lines.append(f"  🎯 {m.get('market_name', '')} (score: {m.get('total_score', '')})")

    if isinstance(reflection, dict):
        quality = reflection.get("quality_score", "N/A")
        summary = reflection.get("summary", "")
        lines.append(f"\n*品質スコア:* {quality}/10")
        if summary:
            lines.append(f"*サマリー:* {summary[:200]}")

        suggestions = reflection.get("improvement_suggestions", [])
        if suggestions:
            lines.append("\n*改善提案:*")
            for s in suggestions[:3]:
                lines.append(f"  💡 {s}")

        risks = reflection.get("risks_identified", [])
        if risks:
            lines.append("\n*リスク:*")
            for r in risks[:3]:
                lines.append(f"  ⚠️ {r}")

        next_actions = reflection.get("next_actions", [])
        if next_actions:
            lines.append("\n*次回アクション:*")
            for a in next_actions[:3]:
                lines.append(f"  📋 {a}")

    # Footer with direct links to key sheets
    settings_url = sheet_urls.get("settings", "")
    if settings_url:
        lines.append(f"\n📋 <{settings_url}|設定シート>")

    notify("\n".join(lines))


# =========================================================================
# Main orchestrator
# =========================================================================
def main():
    # =======================================================================
    # V1 DEPRECATED — このスクリプトはV2で完全廃止されました。
    # orchestrate_v2.py の証拠ベースPASS/FAILゲート方式に移行済みです。
    # =======================================================================
    logger.warning("=" * 60)
    logger.warning("orchestrate_abc0.py はV2で完全廃止されました。")
    logger.warning("orchestrate_v2.py を使用してください。")
    logger.warning("=" * 60)
    update_status(
        "orchestrate_abc0", "success",
        "V1廃止済み — orchestrate_v2.py に移行済み",
    )
    return

    # --- 以下は廃止済みコード（参照用に残置） ---
    start_time = time.time()
    logger.info("=" * 60)
    logger.info("ABC0 自律型パイプライン開始")
    logger.info("=" * 60)
    update_status("orchestrate_abc0", "running", "パイプライン開始")

    try:
        # --- Setup ---
        settings = _load_settings()
        knowledge_context = get_knowledge_summary()
        ceo_profile = settings.get("ceo_profile_json", "")

        # --- 前回の改善提案をコンテキストに注入 ---
        improvement_log = settings.get("pipeline_improvement_log", "")
        if improvement_log:
            logger.info(f"前回の改善提案を読み込み: {improvement_log[:100]}...")
            knowledge_context = (
                f"{knowledge_context}\n\n"
                f"## 前回パイプラインからの改善提案・学び\n"
                f"{improvement_log}"
            )

        steps = []

        # --- Step A: Market Research ---
        result_a = step_a_market_research(settings, knowledge_context)
        steps.append(result_a)
        if result_a["status"] == STEP_FAIL and not result_a.get("data"):
            logger.error("Step A 完全失敗 — パイプライン停止")
            _abort_pipeline(steps, start_time)
            return

        # --- Step P: Pain Extraction ---
        result_p = step_p_pain_extraction(
            result_a.get("markets", []),
            result_a.get("data", []),
        )
        steps.append(result_p)
        pain_context = format_pains_for_scoring(result_p.get("data", []))

        # --- Step B: Market Selection ---
        result_b = step_b_market_selection(settings, knowledge_context, pain_context)
        steps.append(result_b)
        if result_b["status"] == STEP_FAIL and not result_b.get("data"):
            logger.error("Step B 完全失敗 — パイプライン停止")
            _abort_pipeline(steps, start_time)
            return

        # --- Auto-Approve ---
        result_approve = step_auto_approve(settings, result_b.get("data", []))
        steps.append(result_approve)
        auto_approved = result_approve.get("data", [])

        # --- Step C: Competitor Analysis ---
        result_c = step_c_competitor_analysis(settings, knowledge_context)
        steps.append(result_c)

        # --- Step 0: Idea Generation ---
        result_0 = step_0_idea_generation(settings, knowledge_context)
        steps.append(result_0)
        ideas = result_0.get("data", [])

        # --- Step U: Unit Economics ---
        result_u = step_u_unit_economics(
            ideas,
            result_a.get("data", []),
            result_c.get("data", []),
            ceo_profile,
        )
        steps.append(result_u)

        # --- Step E: Checklist Evaluation ---
        result_e = step_e_checklist_evaluation(
            ideas,
            result_a.get("data", []),
            result_c.get("data", []),
            result_u.get("data", []),
            result_p.get("data", []),
            ceo_profile,
        )
        steps.append(result_e)

        # --- Step I: Interview Scripts ---
        result_i = step_i_interview_scripts(
            ideas,
            result_p.get("data", []),
            result_u.get("data", []),
            result_a.get("data", []),
        )
        steps.append(result_i)

        # --- Self-Reflection ---
        elapsed = time.time() - start_time
        total_duration = f"{int(elapsed // 60)}分{int(elapsed % 60)}秒"

        reflection = step_reflection(
            steps, settings, auto_approved, ideas,
            result_u.get("data", []),
            result_e.get("data", []),
            total_duration,
        )

        # --- Report ---
        send_pipeline_report(steps, auto_approved, reflection, total_duration)

        # --- Final status ---
        has_errors = any(s["status"] == STEP_FAIL for s in steps)
        final_status = "error" if has_errors else "success"
        step_summary = ", ".join(
            f"{s['name'].split(':')[0]}: {s.get('count', 0)}件" for s in steps if s.get("count")
        )

        update_status(
            "orchestrate_abc0", final_status,
            f"完了 ({total_duration}) — {step_summary}",
            {
                "total_duration_sec": int(elapsed),
                "quality_score": reflection.get("quality_score", 0) if isinstance(reflection, dict) else 0,
                "steps": {s["name"]: s["status"] for s in steps},
            },
        )
        logger.info(f"ABC0 パイプライン完了: {total_duration}")

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"Pipeline crashed: {e}")
        update_status("orchestrate_abc0", "error", f"致命的エラー: {str(e)}")
        notify(f"🚨 *ABC0パイプライン致命的エラー*\n```{str(e)[:500]}```")
        raise


def _abort_pipeline(steps: list, start_time: float):
    """Abort pipeline, send notification, update status."""
    elapsed = time.time() - start_time
    total_duration = f"{int(elapsed // 60)}分{int(elapsed % 60)}秒"

    # Get sheet URLs for failed steps
    try:
        all_sheet_names = set()
        for s in steps:
            step_key = s["name"].split(":")[0]
            for sn in STEP_SHEET_MAP.get(step_key, []):
                all_sheet_names.add(sn)
        sheet_urls = get_sheet_urls(list(all_sheet_names)) if all_sheet_names else {}
    except Exception:
        sheet_urls = {}

    lines = ["🚨 *ABC0パイプライン停止*", f"⏱️ {total_duration}", ""]
    for s in steps:
        step_key = s["name"].split(":")[0]
        relevant = STEP_SHEET_MAP.get(step_key, [])
        link_parts = [f"<{sheet_urls[sn]}|📊{sn}>" for sn in relevant if sn in sheet_urls]
        link_str = f"  → {' '.join(link_parts)}" if link_parts else ""
        lines.append(f"  {s['status']} {s['name']}{link_str}")
        if s.get("errors"):
            for e in s["errors"][:3]:
                lines.append(f"    → {e}")

    notify("\n".join(lines))
    update_status("orchestrate_abc0", "error", f"パイプライン停止 ({total_duration})")


if __name__ == "__main__":
    main()
