"""
email_sender.py — Gmail API email sending with CEO approval flow.

Flow:
  1. Generate email content (pain_statement + deliverable)
  2. Write to mail_approval sheet (ceo_decision=pending)
  3. CEO marks GO/STOP in sheet
  4. Separate job sends approved emails → mail_sent_log

Uses Gmail API with OAuth2 (not service account).
"""
from __future__ import annotations

import base64
import json
import random
import time
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    CREDENTIALS_DIR,
    GMAIL_SENDER_EMAIL,
    get_logger,
)
from utils.sheets_client import (
    get_all_rows,
    append_rows,
    get_setting,
    find_row_index,
    update_cell,
)

logger = get_logger("email_sender", "email_sender.log")

JST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# Gmail API Client
# ---------------------------------------------------------------------------

_gmail_service = None


def _get_gmail_service():
    global _gmail_service
    if _gmail_service is not None:
        return _gmail_service

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    import pickle

    SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
    token_path = CREDENTIALS_DIR / "gmail_token.pickle"
    creds_path = CREDENTIALS_DIR / "gmail_credentials.json"

    creds = None
    if token_path.exists():
        with open(token_path, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                raise FileNotFoundError(
                    f"Gmail credentials not found at {creds_path}. "
                    "Please set up OAuth2 credentials."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, "wb") as f:
            pickle.dump(creds, f)

    _gmail_service = build("gmail", "v1", credentials=creds)
    return _gmail_service


def _send_email(to: str, subject: str, body: str, sender: str = "") -> str:
    service = _get_gmail_service()
    sender = sender or GMAIL_SENDER_EMAIL

    msg = MIMEText(body, "plain", "utf-8")
    msg["to"] = to
    msg["from"] = sender
    msg["subject"] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(
        userId="me",
        body={"raw": raw},
    ).execute()

    return result.get("id", "")


# ---------------------------------------------------------------------------
# Email Content Generation
# ---------------------------------------------------------------------------

def generate_email_content(
    offer: dict,
    company_name: str,
    sender_name: str = "",
) -> dict:
    from utils.claude_client import generate_json_with_retry

    offer_name = offer.get("offer_name", "")
    deliverable = offer.get("deliverable", "")
    replaces = offer.get("replaces", "")
    price = offer.get("price", "")
    payer = offer.get("payer", "")

    prompt = (
        f"以下のオファーについて、{company_name}の{payer}向けの営業メールを作成してください。\n\n"
        f"オファー名: {offer_name}\n"
        f"提供物: {deliverable}\n"
        f"代替対象: {replaces}\n"
        f"価格: {price}\n"
        f"送信者名: {sender_name}\n\n"
        f"ルール:\n"
        f"- 件名は20文字以内\n"
        f"- 本文は200文字以内\n"
        f"- 「AI」という単語を使わない\n"
        f"- 具体的な痛みに言及する\n"
        f"- 1つの明確なCTA（返信 or URL）\n\n"
        f'JSON: {{"subject": "件名", "body": "本文"}}'
    )

    result = generate_json_with_retry(
        prompt=prompt,
        system="簡潔で効果的な営業メールを書いてください。",
        max_tokens=1024,
        temperature=0.5,
        max_retries=1,
    )

    if isinstance(result, list):
        result = result[0] if result else {}

    return result


# ---------------------------------------------------------------------------
# CEO Approval Flow
# ---------------------------------------------------------------------------

def submit_for_approval(
    run_id: str,
    business_id: str,
    offer: dict,
    targets: list[dict],
    sender_name: str = "",
) -> int:
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    rows = []

    for target in targets:
        company = target.get("company_name", "")
        email = target.get("email", "")

        content = generate_email_content(
            offer=offer,
            company_name=company,
            sender_name=sender_name,
        )

        rows.append([
            run_id,
            business_id,
            offer.get("offer_name", ""),
            company,
            email,
            content.get("subject", ""),
            content.get("body", ""),
            "pending",
            "",
            now,
        ])

        time.sleep(0.5)

    if rows:
        try:
            append_rows("mail_approval", rows)
        except Exception as e:
            logger.warning(f"Failed to save mail_approval rows: {e}")

    logger.info(f"CEO承認申請: {len(rows)}件 ({offer.get('offer_name', '')})")
    return len(rows)


# ---------------------------------------------------------------------------
# Send Approved Emails
# ---------------------------------------------------------------------------

def send_approved_emails(run_id: str = "", dry_run: bool = False) -> int:
    daily_limit = int(get_setting("mail_daily_limit") or 50)

    rows = get_all_rows("mail_approval")
    approved = [
        r for r in rows
        if r.get("ceo_decision") == "approved"
    ]

    if run_id:
        approved = [r for r in approved if r.get("run_id") == run_id]

    # Check already sent today
    sent_rows = get_all_rows("mail_sent_log")
    today = datetime.now(JST).strftime("%Y-%m-%d")
    sent_today = sum(
        1 for r in sent_rows
        if r.get("sent_at", "").startswith(today)
    )

    remaining = daily_limit - sent_today
    if remaining <= 0:
        logger.warning(f"日次送信上限到達: {sent_today}/{daily_limit}")
        return 0

    to_send = approved[:remaining]
    sent_count = 0

    for item in to_send:
        email = item.get("target_email", "")
        subject = item.get("subject", "")
        body = item.get("body_text", "")

        if not email or not subject or not body:
            continue

        if dry_run:
            logger.info(f"[DRY RUN] Would send to {email}: {subject}")
            sent_count += 1
            continue

        try:
            msg_id = _send_email(to=email, subject=subject, body=body)
            now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")

            # Record sent
            append_rows("mail_sent_log", [[
                item.get("run_id", ""),
                item.get("business_id", ""),
                email,
                subject,
                now,
                msg_id,
                "sent",
                "",
            ]])

            sent_count += 1
            logger.info(f"送信成功: {email} ({msg_id})")

            # Random delay 30-90 seconds
            delay = random.randint(30, 90)
            time.sleep(delay)

        except Exception as e:
            logger.error(f"送信失敗: {email}: {e}")
            now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
            try:
                append_rows("mail_sent_log", [[
                    item.get("run_id", ""),
                    item.get("business_id", ""),
                    email,
                    subject,
                    now,
                    "",
                    "failed",
                    str(e)[:200],
                ]])
            except Exception:
                pass

    logger.info(f"メール送信完了: {sent_count}/{len(to_send)}件 (本日合計: {sent_today + sent_count})")
    return sent_count
