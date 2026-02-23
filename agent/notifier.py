"""
Agent notification dispatcher — sends agent results to Google Chat and Slack.
Simplified version of scripts/utils/slack_notifier.py for the agent context.
"""

from __future__ import annotations

import json
import requests

from agent.config import GCHAT_WEBHOOK_URL, SLACK_WEBHOOK_URL, get_logger

logger = get_logger(__name__)


def notify(title: str, body: str, is_error: bool = False) -> None:
    """
    Send a notification to Google Chat and Slack.

    Args:
        title: Short title/header for the notification.
        body: Main message body (plain text or markdown).
        is_error: If True, prefix with ❌, otherwise ✅.
    """
    icon = "❌" if is_error else "✅"
    message = f"{icon} *[Agent] {title}*\n\n{body}"

    _send_gchat(message)
    _send_slack(message)


def _send_gchat(text: str) -> bool:
    """Post a message to Google Chat via webhook."""
    if not GCHAT_WEBHOOK_URL:
        logger.debug("GCHAT_WEBHOOK_URL not set, skipping Google Chat")
        return False

    try:
        resp = requests.post(
            GCHAT_WEBHOOK_URL,
            json={"text": text},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("Google Chat notification sent")
        return True
    except Exception as e:
        logger.warning("Google Chat notification failed: %s", e)
        return False


def _send_slack(text: str) -> bool:
    """Post a message to Slack via webhook."""
    if not SLACK_WEBHOOK_URL:
        logger.debug("SLACK_WEBHOOK_URL not set, skipping Slack")
        return False

    try:
        resp = requests.post(
            SLACK_WEBHOOK_URL,
            json={"text": text},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("Slack notification sent")
        return True
    except Exception as e:
        logger.warning("Slack notification failed: %s", e)
        return False
