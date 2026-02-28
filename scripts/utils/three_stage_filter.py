"""
three_stage_filter.py — 3-stage quality filter for pipeline items.

Stage 1: Generation (already done by caller)
Stage 2: Critical Review — 5 harsh questions per item (AI)
Stage 3: Existence Check — Gemini grounding to verify real-world existence

Gate truth table:
  review_pass=True  AND exists=True  → PASS
  review_pass=True  AND exists=False → PASS (new concept, warning)
  review_pass=False AND exists=True  → FAIL (review failed)
  review_pass=False AND exists=False → FAIL (no basis)

Called by orchestrate_v2.py for Phase A (Layer1), Phase B (Layer2), Phase D (competitors).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TEMPLATES_DIR, get_logger
from utils.claude_client import generate_json_with_retry

logger = get_logger("three_stage_filter", "three_stage_filter.log")
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

BATCH_SIZE = 10


def critical_review(
    items: list[dict],
    item_type: str,
    context: str = "",
) -> list[dict]:
    """Stage 2: Ask 5 critical questions about each item batch.

    Args:
        items: list of dicts (types, combos, or competitors)
        item_type: "layer1_type" | "layer2_combo" | "competitor_win"
        context: construction industry context string

    Returns:
        items with 'review_pass' (bool) and 'review_reason' (str) added
    """
    if not items:
        return items

    template = jinja_env.get_template("critical_review_prompt.j2")
    reviewed = []

    for i in range(0, len(items), BATCH_SIZE):
        batch = items[i:i + BATCH_SIZE]

        prompt = template.render(
            items_json=json.dumps(batch, ensure_ascii=False, default=str),
            item_type=item_type,
            construction_context=context,
        )

        try:
            result = generate_json_with_retry(
                prompt=prompt,
                system="批判的レビュアーとして、各アイテムの実現可能性を厳しく評価してください。",
                max_tokens=8192,
                temperature=0.2,
                max_retries=2,
            )

            if isinstance(result, dict):
                result = [result]

            review_map = {}
            for r in result:
                idx = r.get("index", r.get("item_index", -1))
                review_map[idx] = r

            for j, item in enumerate(batch):
                review = review_map.get(j, {})
                item["review_pass"] = review.get("pass", False)
                item["review_reason"] = review.get("reason", "レビュー結果なし")
                reviewed.append(item)

        except Exception as e:
            logger.warning(f"Critical review batch {i//BATCH_SIZE + 1} failed: {e}")
            for item in batch:
                item["review_pass"] = True
                item["review_reason"] = f"レビュースキップ（エラー: {e}）"
                reviewed.append(item)

        if i + BATCH_SIZE < len(items):
            time.sleep(1.0)

    passed = sum(1 for it in reviewed if it.get("review_pass"))
    logger.info(f"Critical review ({item_type}): {len(reviewed)}件 → {passed}件通過")
    return reviewed


def existence_check(
    items: list[dict],
    item_type: str,
) -> list[dict]:
    """Stage 3: Verify real-world existence via Gemini grounding.

    Args:
        items: list of dicts with 'review_pass' already set
        item_type: "layer1_type" | "layer2_combo" | "competitor_win"

    Returns:
        items with 'exists_check' (bool) added
    """
    if not items:
        return items

    template = jinja_env.get_template("existence_check_prompt.j2")
    checked = []

    for i in range(0, len(items), BATCH_SIZE):
        batch = items[i:i + BATCH_SIZE]

        prompt = template.render(
            items_json=json.dumps(batch, ensure_ascii=False, default=str),
            item_type=item_type,
        )

        try:
            result = generate_json_with_retry(
                prompt=prompt,
                system="Google検索で実在を確認してください。",
                max_tokens=4096,
                temperature=0.1,
                max_retries=2,
                use_search=True,
            )

            if isinstance(result, dict):
                result = [result]

            check_map = {}
            for r in result:
                idx = r.get("index", r.get("item_index", -1))
                check_map[idx] = r

            for j, item in enumerate(batch):
                check = check_map.get(j, {})
                item["exists_check"] = check.get("exists", False)
                item["exists_evidence"] = check.get("evidence", "")
                checked.append(item)

        except Exception as e:
            logger.warning(f"Existence check batch {i//BATCH_SIZE + 1} failed: {e}")
            for item in batch:
                item["exists_check"] = False
                item["exists_evidence"] = f"チェックスキップ（エラー: {e}）"
                checked.append(item)

        if i + BATCH_SIZE < len(items):
            time.sleep(1.5)

    found = sum(1 for it in checked if it.get("exists_check"))
    logger.info(f"Existence check ({item_type}): {len(checked)}件 → {found}件実在確認")
    return checked


def apply_three_stage_gate(
    items: list[dict],
    item_type: str,
    context: str = "",
) -> tuple[list[dict], list[dict]]:
    """Apply full 3-stage filter pipeline.

    Args:
        items: raw generated items
        item_type: "layer1_type" | "layer2_combo" | "competitor_win"
        context: construction industry context

    Returns:
        (passed_items, failed_items)
    """
    if not items:
        return [], []

    original_count = len(items)

    # Stage 2: Critical review
    items = critical_review(items, item_type, context)

    # Stage 3: Existence check
    items = existence_check(items, item_type)

    # Gate decision
    passed = []
    failed = []

    for item in items:
        review_ok = item.get("review_pass", False)
        exists = item.get("exists_check", False)

        if review_ok and exists:
            item["gate_result"] = "PASS"
            passed.append(item)
        elif review_ok and not exists:
            item["gate_result"] = "PASS_NEW"
            passed.append(item)
        elif not review_ok and exists:
            item["gate_result"] = "FAIL_REVIEW"
            failed.append(item)
        else:
            item["gate_result"] = "FAIL_NO_BASIS"
            failed.append(item)

    logger.info(
        f"3-stage gate ({item_type}): "
        f"{original_count} → {len(passed)} PASS, {len(failed)} FAIL"
    )
    return passed, failed
