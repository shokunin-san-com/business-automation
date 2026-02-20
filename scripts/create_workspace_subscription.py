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
            "includeResource": True,
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


def delete_subscription(creds, sub_name):
    """Delete a subscription by name."""
    url = f"https://workspaceevents.googleapis.com/v1/{sub_name}"
    resp = requests.delete(
        url,
        headers={"Authorization": f"Bearer {creds.token}"},
    )
    return resp


if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("Workspace Events API Subscription Manager")
    print("=" * 60)
    print(f"Space: {SPACE_NAME}")
    print(f"Topic: {PUBSUB_TOPIC}")
    print()

    print("1. Authenticating user...")
    creds = get_user_credentials()
    print(f"  Authenticated successfully")
    print()

    # Check for --recreate flag
    recreate = "--recreate" in sys.argv

    if recreate:
        print("2. Listing existing subscriptions...")
        resp_list = list_subscriptions(creds)
        if resp_list.status_code == 200:
            subs = resp_list.json().get("subscriptions", [])
            for sub in subs:
                sub_name = sub.get("name", "")
                print(f"  Deleting: {sub_name}")
                del_resp = delete_subscription(creds, sub_name)
                print(f"  Delete status: {del_resp.status_code}")
                if del_resp.status_code not in (200, 202):
                    print(f"  Response: {del_resp.text[:200]}")
            if not subs:
                print("  No existing subscriptions found.")
        print()
        print("3. Creating new subscription (includeResource=True)...")
    else:
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
        print("Subscription already exists.")
        print("Use --recreate flag to delete and recreate.")
        print()
        print("Listing existing subscriptions...")
        resp2 = list_subscriptions(creds)
        print(f"  Status: {resp2.status_code}")
        try:
            print(f"  Response: {json.dumps(resp2.json(), indent=2)}")
        except Exception:
            print(f"  Response: {resp2.text}")
    else:
        print(f"Failed with status {resp.status_code}")
        print("Check the error message above.")
