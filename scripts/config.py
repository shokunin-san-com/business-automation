"""
Configuration management — loads .env and defines paths.
"""

from __future__ import annotations

import os
import logging
from pathlib import Path

from dotenv import load_dotenv

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
LP_CONTENT_DIR = DATA_DIR / "lp_content"
LOGS_DIR = DATA_DIR / "logs"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
CREDENTIALS_DIR = PROJECT_ROOT / "credentials"

# Ensure directories exist
for d in [LP_CONTENT_DIR, LOGS_DIR, CREDENTIALS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Cloud environment: write service account JSON from env var if not present locally
_sa_json_env = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
_sa_local_path = CREDENTIALS_DIR / "service_account.json"
if _sa_json_env and not _sa_local_path.exists():
    import json as _json
    _wrote = False
    # Try multiple parsing strategies for Secret Manager JSON
    for _strict in (True, False):
        if _wrote:
            break
        try:
            _parsed = _json.loads(_sa_json_env, strict=_strict)
            _sa_local_path.write_text(_json.dumps(_parsed, indent=2), encoding="utf-8")
            _wrote = True
        except _json.JSONDecodeError:
            pass
    if not _wrote:
        # Last resort: write raw (may have literal \n that google-auth can't parse)
        _sa_local_path.write_text(_sa_json_env, encoding="utf-8")

# --- Gemini ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# --- Google ---
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "")
GA_TRACKING_ID = os.getenv("GA_TRACKING_ID", "")
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")

# --- Twitter / X ---
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY", "")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET", "")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET", "")

# --- LinkedIn ---
LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")
LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN", "")

# --- Slack ---
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

# --- Google Chat ---
GCHAT_WEBHOOK_URL = os.getenv("GCHAT_WEBHOOK_URL", "")

# --- Gmail API ---
GMAIL_SENDER_EMAIL = os.getenv("GMAIL_SENDER_EMAIL", "info02@shokunin-san.com")

# --- Cost tracking ---
COST_WARN_JPY = int(os.getenv("COST_WARN_JPY", "25000"))
COST_HARD_STOP_JPY = int(os.getenv("COST_HARD_STOP_JPY", "30000"))

# --- Business ---
YOUR_COMPANY_NAME = os.getenv("YOUR_COMPANY_NAME", "MarketProbe Project")
YOUR_NAME = os.getenv("YOUR_NAME", "みゆ")
YOUR_EMAIL = os.getenv("YOUR_EMAIL", "info02@shokunin-san.com")

# --- Logging ---
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"


def get_logger(name: str, log_file: str | None = None) -> logging.Logger:
    """Create a logger that writes to console and optionally to a file."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    if log_file:
        fh = logging.FileHandler(LOGS_DIR / log_file, encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger
