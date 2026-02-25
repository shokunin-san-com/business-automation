"""
Notification dispatcher — sends to Slack and Google Chat in parallel.

Supports plain text and Slack Block Kit (interactive buttons).
Google Chat receives plain-text version with Slack mrkdwn converted.
"""
from __future__ import annotations

import json
import re
import requests

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import SLACK_WEBHOOK_URL, GCHAT_WEBHOOK_URL, get_logger

logger = get_logger(__name__)


def _slack_mrkdwn_to_gchat(text: str) -> str:
    """Convert Slack mrkdwn to Google Chat compatible format.

    Google Chat supports a subset of markdown:
      - *bold* stays as *bold*
      - ~strike~ → ~strike~ (same)
      - `code` stays as `code`
      - :emoji: → strip colons for readability
      - <URL|label> → label (URL) — Google Chat auto-links URLs
    """
    # Convert Slack link format <URL|label> → label (URL)
    text = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"\2 ( \1 )", text)
    # Convert bare Slack links <URL> → URL
    text = re.sub(r"<(https?://[^>]+)>", r"\1", text)

    # Convert Slack emoji shortcodes to unicode or plain text
    emoji_map = {
        ":mega:": "📢", ":warning:": "⚠️", ":no_entry:": "🛑",
        ":x:": "❌", ":white_check_mark:": "✅", ":rocket:": "🚀",
        ":chart_with_upwards_trend:": "📈", ":bulb:": "💡",
        ":gear:": "⚙️", ":memo:": "📝",
    }
    for code, emoji in emoji_map.items():
        text = text.replace(code, emoji)
    # Strip remaining :emoji_name: patterns
    text = re.sub(r":([a-z0-9_+-]+):", r"\1", text)
    return text


def _send_to_slack(text: str, blocks: list | None = None) -> bool:
    """Post a message to Slack via webhook."""
    if not SLACK_WEBHOOK_URL:
        logger.debug("SLACK_WEBHOOK_URL not set, skipping Slack")
        return False

    payload: dict = {"text": text}
    if blocks:
        payload["blocks"] = blocks

    try:
        resp = requests.post(
            SLACK_WEBHOOK_URL,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Slack notification sent")
            return True
        else:
            logger.error(f"Slack webhook returned {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Slack notification failed: {e}")
        return False


def _send_to_gchat(text: str) -> bool:
    """Post a message to Google Chat via webhook."""
    if not GCHAT_WEBHOOK_URL:
        logger.debug("GCHAT_WEBHOOK_URL not set, skipping Google Chat")
        return False

    gchat_text = _slack_mrkdwn_to_gchat(text)
    payload = {"text": gchat_text}

    try:
        resp = requests.post(
            GCHAT_WEBHOOK_URL,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json; charset=UTF-8"},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Google Chat notification sent")
            return True
        else:
            logger.error(f"Google Chat webhook returned {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Google Chat notification failed: {e}")
        return False


def send_message(text: str, blocks: list | None = None) -> bool:
    """Post a message to Slack and Google Chat (parallel dispatch).

    Returns True if at least one channel succeeded.
    """
    slack_ok = _send_to_slack(text, blocks)
    gchat_ok = _send_to_gchat(text)

    if not slack_ok and not gchat_ok:
        logger.warning("Both Slack and Google Chat notifications failed")
        return False
    return True


def send_idea_approval_request(idea: dict, dashboard_url: str) -> bool:
    """Send a notification with Approve/Reject info for a business idea.

    Slack: Block Kit with interactive buttons.
    Google Chat: Plain text with dashboard link.

    Args:
        idea: dict with id, name, category, description, target_audience
        dashboard_url: Link to the dashboard

    Returns True on success.
    """
    idea_id = idea.get("id", "")
    idea_name = idea.get("name", "Unknown")
    category = idea.get("category", "")
    description = idea.get("description", "")
    target = idea.get("target_audience", "")

    # Slack Block Kit
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"\U0001F4A1 新しい事業案: {idea_name}",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*カテゴリ:*\n{category}"},
                {"type": "mrkdwn", "text": f"*ターゲット:*\n{target}"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*概要:*\n{description[:300]}{'...' if len(description) > 300 else ''}",
            },
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "\u2705 承認する"},
                    "style": "primary",
                    "action_id": "approve_idea",
                    "value": idea_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "\u274C 却下する"},
                    "style": "danger",
                    "action_id": "reject_idea",
                    "value": idea_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "\U0001F4CB ダッシュボードで確認"},
                    "url": dashboard_url,
                    "action_id": "open_dashboard",
                },
            ],
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "ダッシュボードで承認・却下できます",
                },
            ],
        },
    ]

    # Plain text for fallback (Slack) and Google Chat
    plain_text = (
        f"💡 *新しい事業案: {idea_name}*\n\n"
        f"*カテゴリ:* {category}\n"
        f"*ターゲット:* {target}\n"
        f"*概要:* {description[:200]}{'...' if len(description) > 200 else ''}\n\n"
        f"ダッシュボードで承認・却下してください: {dashboard_url}"
    )

    slack_ok = _send_to_slack(plain_text, blocks)
    gchat_ok = _send_to_gchat(plain_text)

    return slack_ok or gchat_ok
