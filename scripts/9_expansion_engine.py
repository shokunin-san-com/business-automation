"""
9_expansion_engine.py — Detect winning patterns and generate scaling plans.

Phase 3 of CEO strategy: scale what works.
Scheduled to run daily at 3:00 AM JST (after learning_engine).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_logger
from utils.expansion_engine import (
    detect_winning_patterns,
    generate_sop,
    generate_budget_recommendation,
    save_winning_pattern,
    log_expansion_action,
)
from utils.slack_notifier import send_message as slack_notify
from utils.status_writer import update_status

logger = get_logger("expansion_engine", "expansion_engine.log")


def main():
    logger.info("=== Expansion engine start ===")
    update_status("9_expansion_engine", "running", "勝ちパターン検出中...")

    try:
        # 1. Detect winning patterns
        candidates = detect_winning_patterns()

        if not candidates:
            logger.info("No winning patterns detected")
            update_status("9_expansion_engine", "success", "勝ちパターンなし", {
                "patterns_detected": 0,
            })
            return

        logger.info(f"Found {len(candidates)} winning pattern candidates")

        # 2. Generate SOP + budget for each
        update_status("9_expansion_engine", "running", f"{len(candidates)}件のSOP生成中...")
        patterns_saved = 0

        for pattern in candidates:
            try:
                # Check if pattern already exists
                from utils.sheets_client import get_all_rows
                existing = get_all_rows("winning_patterns")
                already_exists = any(
                    r.get("business_id") == pattern["business_id"]
                    and r.get("status") not in ("archived", "saturated")
                    for r in existing
                )
                if already_exists:
                    logger.info(f"Pattern already exists for {pattern['business_id']}, skipping")
                    continue

                # Generate SOP
                sop = generate_sop(pattern)
                budget_rec = generate_budget_recommendation(pattern)

                # Save pattern
                pattern_id = save_winning_pattern(pattern, sop, budget_rec)
                log_expansion_action(
                    pattern_id=pattern_id,
                    business_id=pattern["business_id"],
                    action_type="pattern_detected",
                    action_detail=f"市場: {pattern['micro_market']}, オファー: {pattern['offer_name']}, 成約率: {pattern['deal_rate']:.1%}",
                )
                patterns_saved += 1

            except Exception as e:
                logger.error(f"Failed to process pattern for {pattern.get('business_id')}: {e}")
                continue

        # 3. Slack notification
        if patterns_saved > 0:
            msg_parts = [f":rocket: *拡張エンジン* — {patterns_saved}件の勝ちパターン検出\n"]
            for p in candidates[:5]:
                type_label = {
                    "quick_win": "即効型",
                    "steady_growth": "安定成長",
                    "high_potential": "高ポテンシャル",
                }.get(p.get("pattern_type", ""), p.get("pattern_type", ""))
                msg_parts.append(
                    f"• *{p.get('micro_market', '?')}* [{type_label}] "
                    f"— 成約率 {p.get('deal_rate', 0):.0%}, "
                    f"問い合わせ {p.get('total_inquiries', 0)}件"
                )
            slack_notify("\n".join(msg_parts))

        update_status("9_expansion_engine", "success", f"{patterns_saved}件パターン検出", {
            "patterns_detected": patterns_saved,
            "sops_generated": patterns_saved,
        })
        logger.info(f"=== Expansion engine complete: {patterns_saved} patterns ===")

    except Exception as e:
        update_status("9_expansion_engine", "error", str(e))
        logger.error(f"Expansion engine failed: {e}")
        raise


if __name__ == "__main__":
    main()
