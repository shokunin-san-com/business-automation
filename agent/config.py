"""
Agent configuration — loads environment variables for the autonomous agent.
Raises ValueError on missing required variables to fail fast.
"""

from __future__ import annotations

import json
import os
import logging
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2.service_account import Credentials as SACredentials

# Paths
AGENT_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = AGENT_ROOT.parent
CREDENTIALS_DIR = PROJECT_ROOT / "credentials"
load_dotenv(PROJECT_ROOT / ".env")

# --- Required GCP settings ---
GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
if not GCP_PROJECT_ID:
    raise ValueError("GCP_PROJECT_ID is required")

GCP_REGION = os.environ.get("GCP_REGION", "asia-northeast1")

# --- API Keys ---
CLAUDE_API_KEY = (
    os.environ.get("CLAUDE_API_KEY", "")
    or os.environ.get("ANTHROPIC_API_KEY", "")
)
if not CLAUDE_API_KEY:
    raise ValueError("CLAUDE_API_KEY or ANTHROPIC_API_KEY is required")

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")

# --- Google Sheets ---
GOOGLE_SHEETS_ID = os.environ.get("GOOGLE_SHEETS_ID", "")
if not GOOGLE_SHEETS_ID:
    raise ValueError("GOOGLE_SHEETS_ID is required")

# --- Notifications ---
GCHAT_WEBHOOK_URL = os.environ.get("GCHAT_WEBHOOK_URL", "")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

# --- GitHub (optional — only needed for code tasks) ---
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")
GITHUB_DEFAULT_BRANCH = os.environ.get("GITHUB_DEFAULT_BRANCH", "main")

# --- Logging ---
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"


def get_logger(name: str) -> logging.Logger:
    """Create a console logger for agent modules."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)
    return logger


def get_gcp_credentials(scopes: list[str] | None = None) -> SACredentials:
    """
    Load GCP service account credentials.
    Tries: 1) GOOGLE_SERVICE_ACCOUNT_JSON env var, 2) credentials/service_account.json file.
    Matches the existing pipeline authentication pattern from scripts/utils/sheets_client.py.
    """
    # Try env var first (Cloud Run injects via Secret Manager)
    sa_json_env = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if sa_json_env:
        try:
            info = json.loads(sa_json_env, strict=False)
            return SACredentials.from_service_account_info(info, scopes=scopes)
        except Exception:
            pass  # Fall through to file

    # Fallback to file
    sa_path = CREDENTIALS_DIR / "service_account.json"
    if not sa_path.exists():
        raise FileNotFoundError(
            f"Service account JSON not found: {sa_path}\n"
            "Place your GCP service account key there, "
            "or set GOOGLE_SERVICE_ACCOUNT_JSON env var."
        )
    return SACredentials.from_service_account_file(str(sa_path), scopes=scopes)
