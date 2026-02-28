"""
email_target_collector.py — Collect target company email addresses via Gemini grounding.

Uses Gemini with search grounding to find company contact emails
for outreach. Validates email format (RFC 5322 simplified).
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone, timedelta

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_logger
from utils.claude_client import generate_json_with_retry
from utils.sheets_client import append_rows

logger = get_logger("email_target_collector", "email_target_collector.log")

JST = timezone(timedelta(hours=9))

EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def _validate_email(email: str) -> bool:
    if not email or not isinstance(email, str):
        return False
    return bool(EMAIL_REGEX.match(email.strip()))


def _collect_batch(
    market_name: str,
    payer: str,
    region: str = "",
    batch_num: int = 1,
    count: int = 20,
) -> list[dict]:
    region_text = f"（地域: {region}）" if region else ""

    prompt = (
        f"「{market_name}」に関連する日本の建設会社・専門工事会社のメールアドレスを"
        f"{count}件収集してください。{region_text}\n\n"
        f"対象: {payer}\n\n"
        f"各社の公式サイト等から問い合わせ先メールアドレスを探してください。\n"
        f"info@、contact@、support@ 等の一般問い合わせアドレスが望ましい。\n\n"
        f"ルール:\n"
        f"- 実在する企業の実在するメールアドレスのみ\n"
        f"- 架空のアドレスは絶対に出さない\n"
        f"- メールアドレスが見つからない企業は省略\n"
        f"- 個人のメールアドレスは除外（会社の代表/問い合わせアドレスのみ）\n\n"
        f"JSON配列で出力:\n"
        f'[{{"company_name": "企業名", "email": "info@example.co.jp", '
        f'"source_url": "https://...", "region": "東京都", "industry": "建設"}}]'
    )

    try:
        result = generate_json_with_retry(
            prompt=prompt,
            system="実在する企業メールアドレスのみ出力してください。",
            max_tokens=8192,
            temperature=0.2,
            max_retries=2,
            use_search=True,
        )

        if isinstance(result, dict):
            result = [result]

        valid = []
        for item in result:
            if not isinstance(item, dict):
                continue
            email = item.get("email", "").strip()
            if _validate_email(email):
                valid.append(item)
            else:
                logger.debug(f"Invalid email skipped: {email}")

        return valid

    except Exception as e:
        logger.warning(f"Email collection batch {batch_num} failed: {e}")
        return []


def collect_emails(
    market_name: str,
    payer: str,
    run_id: str,
    business_id: str = "",
    target_count: int = 50,
    regions: list[str] | None = None,
) -> list[dict]:
    """Collect email targets for a market.

    Returns list of validated email target dicts.
    """
    if regions is None:
        regions = ["東京都", "大阪府", "愛知県", "神奈川県", "埼玉県"]

    all_targets: list[dict] = []
    seen_emails: set[str] = set()

    batch_num = 0
    for region in regions:
        if len(all_targets) >= target_count:
            break

        batch_num += 1
        remaining = target_count - len(all_targets)
        batch_count = min(20, remaining)

        logger.info(f"  収集バッチ {batch_num}: {region} ({batch_count}件)")
        targets = _collect_batch(
            market_name=market_name,
            payer=payer,
            region=region,
            batch_num=batch_num,
            count=batch_count,
        )

        # Dedup by email
        for t in targets:
            email = t.get("email", "").strip().lower()
            if email not in seen_emails:
                seen_emails.add(email)
                all_targets.append(t)

        time.sleep(1.5)

        try:
            from utils.cost_tracker import record_api_call
            record_api_call(
                run_id=run_id, phase="G_email_collect",
                input_tokens=1000, output_tokens=3000,
                used_search=True,
                note=f"region={region}",
            )
        except Exception:
            pass

    # Save to sheet
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for t in all_targets:
        rows.append([
            run_id,
            business_id or run_id[:8],
            t.get("company_name", ""),
            t.get("email", ""),
            t.get("source_url", ""),
            t.get("region", ""),
            t.get("industry", "建設"),
            "new",
            now,
        ])

    if rows:
        try:
            append_rows("email_targets", rows)
        except Exception as e:
            logger.warning(f"Failed to save email targets: {e}")

    logger.info(f"メールアドレス収集完了: {len(all_targets)}件 ({market_name})")
    return all_targets
