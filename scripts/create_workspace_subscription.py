#!/usr/bin/env python3
"""
Create a Workspace Events API subscription for Google Chat space messages.
Uses OAuth 2.0 user authentication (InstalledAppFlow) to authorize.

This allows receiving message events from external spaces via Pub/Sub,
which the Workspace Add-ons framework cannot do.

Usage:
  python scripts/create_workspace_subscription.py
"""

import json
import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request as AuthRequest
from google.oauth2.credentials import Credentials
import requests

# Configuration
PROJECT_ID = "marketprobe-automation"
PUBSUB_TOPIC = f"projects/{PROJECT_ID}/topics/gchat-space-events"
SPACE_NAME = "spaces/AAQA_WcWZmg"  # Market Probe (external space)

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
OAUTH_CLIENT_PATH = os.path.join(BASE_DIR, "credentials", "oauth_desktop_client.json")
TOKEN_PATH = os.path.join(BASE_DIR, "credentials", "oauth_user_token.json")

# Scopes needed for Workspace Events API + Chat
SCOPES = [
    "https://www.googleapis.com/auth/chat.spaces.readonly",
    "https://www.googleapis.com/auth/chat.messages.readonly",
]


def get_user_credentials():
    """Get user OAuth credentials, refreshing or re-authenticating as needed."""
    creds = None

    # Load saved token if exists
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # If no valid credentials, run the OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("  Refreshing expired token...")
            creds.refresh(AuthRequest())
        else:
            print("  Opening browser for authentication...")
            print("  Please sign in with info02@shokunin-san.com")
            flow = InstalledAppFlow.from_client_secrets_file(OAUTH_CLIENT_PATH, SCOPES)
            creds = flow.run_local_server(port=8090)

        # Save the token for future use
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
        print(f"  Token saved to {TOKEN_PATH}")

    return creds


def create_subscription(creds):
    """Create Workspace Events API subscription."""
    url = "https://workspaceevents.googleapis.com/v1/subscriptions"
    payload = {
        "targetResource": f"//chat.googleapis.com/{SPACE_NAME}",
        "eventTypes": [
            "google.workspace.chat.message.v1.created",
        ],
        "notificationEndpoint": {
            "pubsubTopic": PUBSUB_TOPIC,
        },
        "payloadOptions": {
            "includeResource": False,
        },
    }

    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json",
        },
        json=payload,
    )

    return resp


def list_subscriptions(creds):
    """List existing subscriptions for the space."""
    url = "https://workspaceevents.googleapis.com/v1/subscriptions"
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {creds.token}"},
        params={"filter": f'target_resource="//chat.googleapis.com/{SPACE_NAME}"'},
    )
    return resp


if __name__ == "__main__":
    print("=" * 60)
    print("Workspace Events API Subscription Creator")
    print("=" * 60)
    print(f"Space: {SPACE_NAME}")
    print(f"Topic: {PUBSUB_TOPIC}")
    print()

    print("1. Authenticating user...")
    creds = get_user_credentials()
    print(f"  Authenticated successfully")
    print()

    print("2. Creating subscription...")
    resp = create_subscription(creds)
    print(f"  Status: {resp.status_code}")
    try:
        data = resp.json()
        print(f"  Response: {json.dumps(data, indent=2)}")
    except Exception:
        print(f"  Response: {resp.text}")
    print()

    if resp.status_code in (200, 201):
        print("SUCCESS! Subscription created.")
    elif resp.status_code == 409:
        print("Subscription already exists. Listing existing subscriptions...")
        resp2 = list_subscriptions(creds)
        print(f"  Status: {resp2.status_code}")
        try:
            print(f"  Response: {json.dumps(resp2.json(), indent=2)}")
        except Exception:
            print(f"  Response: {resp2.text}")
    else:
        print(f"Failed with status {resp.status_code}")
        print("Check the error message above.")
