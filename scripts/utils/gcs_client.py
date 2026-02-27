"""
Google Cloud Storage client — upload LP content JSON to GCS bucket.
"""

import json
import os
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CREDENTIALS_DIR, get_logger

logger = get_logger(__name__)

GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "marketprobe-automation-lps")


def upload_json(destination_path: str, data: dict) -> str:
    """Upload a JSON dict to GCS.

    Args:
        destination_path: e.g. "lp_content/idea-123.json"
        data: dict to serialize as JSON

    Returns:
        Public URL of the uploaded file.
    """
    try:
        from google.cloud import storage
        from google.oauth2.service_account import Credentials

        sa_path = CREDENTIALS_DIR / "service_account.json"

        # Try env var first (Cloud Run), then local file
        sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        if sa_json:
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                f.write(sa_json)
                tmp_path = f.name
            creds = Credentials.from_service_account_file(tmp_path)
            client = storage.Client(credentials=creds, project=creds.project_id)
            os.unlink(tmp_path)
        elif sa_path.exists():
            creds = Credentials.from_service_account_file(str(sa_path))
            client = storage.Client(credentials=creds, project=creds.project_id)
        else:
            # Application Default Credentials (Cloud Run)
            client = storage.Client()

        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(destination_path)

        # Recursively sanitize string values to remove control characters
        import re

        def _sanitize(obj):
            if isinstance(obj, str):
                return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', obj)
            elif isinstance(obj, dict):
                return {k: _sanitize(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_sanitize(v) for v in obj]
            return obj

        clean_data = _sanitize(data)
        json_str = json.dumps(clean_data, ensure_ascii=False, indent=2)
        blob.upload_from_string(
            json_str.encode("utf-8"),
            content_type="application/json; charset=utf-8",
        )

        url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{destination_path}"
        logger.info(f"Uploaded to GCS: {url}")
        return url

    except ImportError:
        logger.warning("google-cloud-storage not installed, skipping GCS upload")
        return ""
    except Exception as e:
        logger.warning(f"GCS upload failed: {e}")
        return ""
