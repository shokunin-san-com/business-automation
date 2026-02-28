"""
demand_verifier.py — Multi-source demand verification.

3 sources:
  1. Google Suggest API — keyword autocomplete existence
  2. Gemini grounding — search-backed demand signal
  3. SNS/QA pain check — Gemini grounding for pain signals on SNS/QA sites

Keyword grouping: 500+ combos → 100-150 groups (API cost reduction).

Verdict:
  CONFIRMED (2+ sources positive) → PASS
  WEAK      (1 source positive)   → PASS with warning
  NOT_FOUND (0)                   → FAIL
"""
from __future__ import annotations

import json
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_logger
from utils.claude_client import generate_json_with_retry

logger = get_logger("demand_verifier", "demand_verifier.log")

JST = timezone(timedelta(hours=9))

SUGGEST_URL = "http://suggestqueries.google.com/complete/search"


# ---------------------------------------------------------------------------
# Source 1: Google Suggest API
# ---------------------------------------------------------------------------

def _check_suggest(keyword: str) -> dict:
    try:
        params = {
            "client": "firefox",
            "q": keyword,
            "hl": "ja",
        }
        resp = requests.get(SUGGEST_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        suggestions = data[1] if len(data) > 1 else []
        has_suggest = len(suggestions) > 0
        return {
            "source": "suggest",
            "positive": has_suggest,
            "count": len(suggestions),
            "top_suggestions": suggestions[:5],
        }
    except Exception as e:
        logger.debug(f"Suggest API failed for '{keyword}': {e}")
        return {"source": "suggest", "positive": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Source 2: Gemini Grounding (search-backed demand signal)
# ---------------------------------------------------------------------------

def _check_gemini_grounding(keyword: str, context: str = "") -> dict:
    prompt = (
        f"「{keyword}」について、日本の建設業界で実際の需要があるか調べてください。\n"
        f"以下を確認:\n"
        f"1. この種のサービスに実際にお金を払っている企業や個人はいるか\n"
        f"2. 関連する求人、入札情報、導入事例はあるか\n"
        f"3. 関連キーワードの検索トレンドはあるか\n\n"
        f"JSON形式で回答:\n"
        f'{{"has_demand": true/false, "evidence": "具体的な証拠（50文字以内）", '
        f'"confidence": "high/medium/low"}}'
    )

    try:
        result = generate_json_with_retry(
            prompt=prompt,
            system="需要の有無を客観的に判定してください。証拠がなければfalseとしてください。",
            max_tokens=1024,
            temperature=0.2,
            max_retries=1,
            use_search=True,
        )

        if isinstance(result, list):
            result = result[0] if result else {}

        return {
            "source": "gemini_grounding",
            "positive": bool(result.get("has_demand", False)),
            "evidence": result.get("evidence", ""),
            "confidence": result.get("confidence", "low"),
        }
    except Exception as e:
        logger.debug(f"Gemini grounding failed for '{keyword}': {e}")
        return {"source": "gemini_grounding", "positive": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Source 3: SNS/QA Pain Check
# ---------------------------------------------------------------------------

def _check_sns_pain(keyword: str) -> dict:
    prompt = (
        f"「{keyword}」に関する建設業界の「痛み」「困りごと」「不満」をSNS・Q&Aサイトで検索してください。\n"
        f"Twitter/X、知恵袋、はてな、建設業界フォーラム等で、\n"
        f"この領域の課題について実際に投稿している人がいるか確認してください。\n\n"
        f"JSON形式で回答:\n"
        f'{{"has_pain": true/false, "pain_summary": "痛みの要約（50文字以内）", '
        f'"source_type": "SNS/QA/フォーラム"}}'
    )

    try:
        result = generate_json_with_retry(
            prompt=prompt,
            system="実際のSNS/QA投稿に基づいて判定してください。推測ではなく証拠を示してください。",
            max_tokens=1024,
            temperature=0.2,
            max_retries=1,
            use_search=True,
        )

        if isinstance(result, list):
            result = result[0] if result else {}

        return {
            "source": "sns_pain",
            "positive": bool(result.get("has_pain", False)),
            "pain_summary": result.get("pain_summary", ""),
            "source_type": result.get("source_type", ""),
        }
    except Exception as e:
        logger.debug(f"SNS pain check failed for '{keyword}': {e}")
        return {"source": "sns_pain", "positive": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Keyword Grouping
# ---------------------------------------------------------------------------

def _group_keywords(combos: list[dict]) -> list[dict]:
    prompt = (
        "以下のビジネスコンボリストから、類似するものをグループ化してください。\n"
        "1グループ = 1つの需要検証キーワードで代表できるまとまり。\n\n"
        + json.dumps(
            [
                {"combo_id": c.get("combo_id", ""), "business_name": c.get("business_name", "")}
                for c in combos
            ],
            ensure_ascii=False,
        )
        + "\n\nJSON配列で出力:\n"
        '[{"group_id": "G001", "keyword": "代表キーワード", "combo_ids": ["BC-0001", "BC-0002"]}]'
    )

    try:
        result = generate_json_with_retry(
            prompt=prompt,
            system="類似するビジネスを1グループにまとめてください。",
            max_tokens=16384,
            temperature=0.3,
            max_retries=2,
        )
        if isinstance(result, dict):
            result = [result]
        return result
    except Exception as e:
        logger.warning(f"Keyword grouping failed: {e}")
        # Fallback: one group per combo
        return [
            {
                "group_id": f"G{i+1:03d}",
                "keyword": c.get("business_name", ""),
                "combo_ids": [c.get("combo_id", "")],
            }
            for i, c in enumerate(combos)
        ]


# ---------------------------------------------------------------------------
# Main Verification
# ---------------------------------------------------------------------------

def _verify_single(keyword: str) -> dict:
    results = {}

    # Source 1: Suggest API
    results["suggest"] = _check_suggest(keyword)
    time.sleep(0.3)

    # Source 2: Gemini grounding
    results["gemini_grounding"] = _check_gemini_grounding(keyword)
    time.sleep(1.0)

    # Source 3: SNS pain
    results["sns_pain"] = _check_sns_pain(keyword)
    time.sleep(1.0)

    # Verdict
    positive_count = sum(
        1 for v in results.values() if v.get("positive", False)
    )

    if positive_count >= 2:
        verdict = "CONFIRMED"
    elif positive_count == 1:
        verdict = "WEAK"
    else:
        verdict = "NOT_FOUND"

    return {
        "keyword": keyword,
        "verdict": verdict,
        "positive_count": positive_count,
        "details": results,
    }


def verify_batch(
    combos: list[dict],
    run_id: str,
    max_groups: int = 150,
) -> tuple[list[dict], list[dict]]:
    """Verify demand for a batch of combos.

    Returns (passed_combos, all_results) where passed_combos have
    verdict CONFIRMED or WEAK.
    """
    from utils.sheets_client import append_rows

    logger.info(f"需要検証開始: {len(combos)} combos")

    # Group keywords
    groups = _group_keywords(combos)
    if len(groups) > max_groups:
        groups = groups[:max_groups]
    logger.info(f"キーワードグループ: {len(groups)}グループ")

    # Build combo_id → combo lookup
    combo_map = {c.get("combo_id", ""): c for c in combos}

    all_results: list[dict] = []
    passed_combo_ids: set[str] = []

    for i, group in enumerate(groups):
        keyword = group.get("keyword", "")
        group_id = group.get("group_id", f"G{i+1:03d}")
        combo_ids = group.get("combo_ids", [])

        logger.info(f"  [{i+1}/{len(groups)}] {keyword}")
        vr = _verify_single(keyword)
        vr["group_id"] = group_id
        vr["combo_ids"] = combo_ids

        all_results.append(vr)

        if vr["verdict"] in ("CONFIRMED", "WEAK"):
            passed_combo_ids.extend(combo_ids)

        # Save to sheet
        now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
        try:
            row = [
                run_id,
                group_id,
                keyword,
                json.dumps(vr["details"].get("suggest", {}), ensure_ascii=False),
                json.dumps(vr["details"].get("gemini_grounding", {}), ensure_ascii=False),
                json.dumps(vr["details"].get("sns_pain", {}), ensure_ascii=False),
                vr["verdict"],
                json.dumps({"combo_ids": combo_ids, "positive_count": vr["positive_count"]}, ensure_ascii=False),
                now,
            ]
            append_rows("demand_verification_log", [row])
        except Exception as e:
            logger.warning(f"Failed to save demand verification: {e}")

        try:
            from utils.cost_tracker import record_api_call
            record_api_call(
                run_id=run_id, phase="C_demand",
                input_tokens=500, output_tokens=500,
                used_search=True,
                note=f"group={group_id}",
            )
        except Exception:
            pass

    # Collect passed combos
    passed_combos = [
        combo_map[cid] for cid in passed_combo_ids
        if cid in combo_map
    ]

    confirmed = sum(1 for r in all_results if r["verdict"] == "CONFIRMED")
    weak = sum(1 for r in all_results if r["verdict"] == "WEAK")
    not_found = sum(1 for r in all_results if r["verdict"] == "NOT_FOUND")

    logger.info(
        f"需要検証完了: CONFIRMED={confirmed}, WEAK={weak}, NOT_FOUND={not_found} "
        f"→ PASS={len(passed_combos)}コンボ"
    )

    return passed_combos, all_results
