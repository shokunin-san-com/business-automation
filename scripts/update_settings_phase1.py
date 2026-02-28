"""
update_settings_phase1.py — Phase 1: Rewrite 6 settings keys + stop V1 pipeline.

Run once to update Google Sheets settings for the Phase 1 transition:
  1. idea_direction_notes → 業務代行型
  2. exploration_markets → "" (disable exploration lane)
  3. target_industries → explicit list
  4. ceo_profile_json → 井上優斗 profile
  5. competitors_per_market → 20
  6. market_direction_notes → 業務代行型方針
  7. sender_name → 井上優斗
  8. sender_email → inoue@shokunin-san.com
  9. sender_company → 職人さんドットコム

Also disables V1 pipeline:
  - v1_pipeline_enabled → false
  - v2_continuous_mode → true

Usage:
    python scripts/update_settings_phase1.py
    python scripts/update_settings_phase1.py --dry-run
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_logger
from utils.sheets_client import get_all_rows, find_row_index, update_cell, append_rows
from utils.slack_notifier import send_message as slack_notify

logger = get_logger("update_settings", "update_settings.log")

# Phase 1 settings values
PHASE1_SETTINGS = {
    "idea_direction_notes": (
        "業務代行型オファーのみ。SaaS・ツール販売は禁止。"
        "「御社の○○業務を丸ごと代行します」形式。"
        "初期費用0円、成果報酬 or 月額固定。"
        "クライアントの社内リソース不要で即日開始できること。"
    ),
    "exploration_markets": "",  # Disable exploration lane
    "target_industries": json.dumps([
        "塗装業",
        "リフォーム業",
        "建設業",
        "不動産業",
        "製造業（中小）",
        "飲食業",
        "美容・エステ",
        "士業（税理士・社労士・行政書士）",
        "介護・福祉",
        "EC・通販事業者",
    ], ensure_ascii=False),
    "ceo_profile_json": json.dumps({
        "name": "井上優斗",
        "name_en": "Yuto Inoue",
        "company": "職人さんドットコム",
        "role": "代表",
        "email": "inoue@shokunin-san.com",
        "expertise": [
            "AI業務自動化",
            "BtoB営業代行",
            "マーケティングオートメーション",
            "中小企業DX支援",
        ],
        "bio": (
            "AI×自動化で中小企業の業務効率化を支援。"
            "営業・マーケティング・バックオフィスの業務代行サービスを提供。"
        ),
    }, ensure_ascii=False),
    "competitors_per_market": "20",
    "market_direction_notes": (
        "業務代行型ビジネスモデル。ターゲットは中小企業の経営者。"
        "競合は人力の代行会社。AI活用による低コスト・高速を武器に差別化。"
        "月額3-10万円の価格帯。初回無料トライアルあり。"
        "1市場1オファーで集中。同時並行は最大3市場。"
    ),
    # Form sales sender info
    "sender_name": "井上優斗",
    "sender_email": "inoue@shokunin-san.com",
    "sender_company": "職人さんドットコム",
    # Pipeline control
    "v1_pipeline_enabled": "false",
    "v2_continuous_mode": "true",
}


def update_settings(dry_run: bool = False) -> dict:
    """Update settings in Google Sheets.

    Returns {"updated": N, "created": N, "skipped": N}.
    """
    counts = {"updated": 0, "created": 0, "skipped": 0}

    for key, value in PHASE1_SETTINGS.items():
        row_idx = find_row_index("settings", "key", key)

        if row_idx:
            if dry_run:
                logger.info(f"[DRY RUN] Would update: {key} = {value[:80]}...")
                counts["skipped"] += 1
            else:
                update_cell("settings", row_idx, 2, value)
                logger.info(f"Updated: {key}")
                counts["updated"] += 1
        else:
            if dry_run:
                logger.info(f"[DRY RUN] Would create: {key} = {value[:80]}...")
                counts["skipped"] += 1
            else:
                append_rows("settings", [[key, value]])
                logger.info(f"Created: {key}")
                counts["created"] += 1

    return counts


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Phase 1: Update settings keys")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()

    logger.info("=== Phase 1 settings update start ===")

    counts = update_settings(dry_run=args.dry_run)

    summary = f"更新{counts['updated']}件 / 新規{counts['created']}件"
    if args.dry_run:
        summary = f"[DRY RUN] スキップ{counts['skipped']}件"

    logger.info(f"=== Phase 1 settings update complete: {summary} ===")

    if not args.dry_run and (counts["updated"] or counts["created"]):
        slack_notify(
            f":gear: *Phase 1 設定更新完了*\n"
            f"{summary}\n"
            f"• V1パイプライン: 停止\n"
            f"• V2連続モード: 有効\n"
            f"• 方向性: 業務代行型\n"
            f"• 送信者: 井上優斗 (inoue@shokunin-san.com)"
        )

    print(f"Done: {summary}")


if __name__ == "__main__":
    main()
