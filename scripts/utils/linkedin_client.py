"""
LinkedIn API wrapper — post content to LinkedIn profile.

Requires LINKEDIN_ACCESS_TOKEN in .env.
Initial token must be obtained via OAuth 2.0 flow (run this file directly).
"""

from __future__ import annotations

import requests

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    LINKEDIN_CLIENT_ID,
    LINKEDIN_CLIENT_SECRET,
    LINKEDIN_ACCESS_TOKEN,
    get_logger,
)

logger = get_logger(__name__)

API_BASE = "https://api.linkedin.com/v2"


def _get_headers() -> dict:
    return {
        "Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _get_profile_urn() -> str | None:
    """Get the authenticated user's LinkedIn profile URN."""
    try:
        resp = requests.get(f"{API_BASE}/me", headers=_get_headers(), timeout=10)
        resp.raise_for_status()
        return f"urn:li:person:{resp.json()['id']}"
    except Exception as e:
        logger.error(f"Failed to get LinkedIn profile: {e}")
        return None


def post_text(text: str) -> dict | None:
    """Post a text-only update to LinkedIn.

    Returns response data or None on failure.
    """
    if not LINKEDIN_ACCESS_TOKEN:
        logger.warning("LINKEDIN_ACCESS_TOKEN not set, skipping")
        return None

    author = _get_profile_urn()
    if not author:
        return None

    payload = {
        "author": author,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }

    try:
        resp = requests.post(
            f"{API_BASE}/ugcPosts",
            json=payload,
            headers=_get_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        post_id = resp.headers.get("x-restli-id", "")
        logger.info(f"LinkedIn post published: {post_id}")
        return {"id": post_id}
    except Exception as e:
        logger.error(f"Failed to post to LinkedIn: {e}")
        return None


# --- OAuth 2.0 token acquisition (run directly) ---

def _run_oauth_flow():
    """Interactive OAuth 2.0 flow to obtain access token."""
    from urllib.parse import urlencode

    redirect_uri = "http://localhost:8000/callback"
    auth_url = "https://www.linkedin.com/oauth/v2/authorization?" + urlencode({
        "response_type": "code",
        "client_id": LINKEDIN_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "w_member_social r_liteprofile",
    })

    print(f"\n1. Open this URL in your browser:\n{auth_url}\n")
    code = input("2. Paste the 'code' parameter from the redirect URL: ").strip()

    resp = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": LINKEDIN_CLIENT_ID,
            "client_secret": LINKEDIN_CLIENT_SECRET,
        },
        timeout=15,
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    print(f"\n3. Add to .env:\nLINKEDIN_ACCESS_TOKEN={token}\n")


if __name__ == "__main__":
    _run_oauth_flow()
