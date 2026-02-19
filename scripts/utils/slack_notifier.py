"""
Slack notification via webhook — supports plain text and Block Kit (interactive buttons).
"""
from __future__ import annotations

import json
import requests

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import SLACK_WEBHOOK_URL, get_logger

logger = get_logger(__name__)


def send_message(text: str, blocks: list | None = None) -> bool:
    """Post a message to Slack via webhook.

    Returns True on success.
    """
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not set, skipping notification")
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


def send_idea_approval_request(idea: dict, dashboard_url: str) -> bool:
    """Send a Slack message with Approve/Reject buttons for a business idea.

    Note: Interactive buttons require a Slack App with Interactivity enabled.
    If using a simple Incoming Webhook (not a Slack App), buttons won't work —
    the message will still display but buttons will be non-functional.
    In that case, users can approve via the Dashboard UI directly.

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

    return send_message(
        text=f"新しい事業案: {idea_name} — 承認してください",
        blocks=blocks,
    )
