"""
PDF Knowledge Base — upload PDFs to GCS, extract summaries via Claude, store in Sheets.

Provides knowledge context injection for idea generation and LP creation pipelines.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CREDENTIALS_DIR, CLAUDE_API_KEY, GEMINI_API_KEY, get_logger
from utils.sheets_client import get_all_rows, append_row, find_row_index

logger = get_logger(__name__)

GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "marketprobe-automation-lps")


def _get_gcs_client():
    """Get authenticated GCS client."""
    from google.cloud import storage
    from google.oauth2.service_account import Credentials

    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    sa_path = CREDENTIALS_DIR / "service_account.json"

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
        client = storage.Client()

    return client


def upload_pdf_to_gcs(pdf_path: str) -> str:
    """Upload a PDF file to GCS knowledge/ directory.

    Returns the GCS path (e.g. 'knowledge/book-a.pdf').
    """
    filename = Path(pdf_path).name
    gcs_path = f"knowledge/{filename}"

    try:
        client = _get_gcs_client()
        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(gcs_path)
        # Use resumable upload with extended timeout for large PDFs
        blob.upload_from_filename(
            pdf_path,
            content_type="application/pdf",
            timeout=600,  # 10 minutes for large files
        )
        logger.info(f"PDF uploaded to GCS: gs://{GCS_BUCKET_NAME}/{gcs_path}")
        return gcs_path
    except Exception as e:
        logger.error(f"GCS upload failed: {e}")
        raise


EXTRACTION_PROMPT = """この書籍/ドキュメントを分析し、以下のJSON形式で出力してください。
JSON以外のテキストは含めないでください。

```json
{
  "title": "書籍タイトル",
  "summary": "全体の要約（300-500文字。主要なフレームワーク、方法論、重要な概念を含める）",
  "chapters": [
    {
      "number": 1,
      "title": "章タイトル",
      "summary": "章の要約（100-200文字。具体的なフレームワーク名、手法、キーコンセプトを含める）"
    }
  ],
  "key_frameworks": ["フレームワーク名1", "フレームワーク名2"],
  "applicable_to": "この書籍の知識が特に有用な事業フェーズや活動（50-100文字）"
}
```"""

# Claude API max request size ~30MB base64. Use Gemini for larger files.
CLAUDE_MAX_FILE_SIZE_MB = 25


def _extract_with_gemini(pdf_path: str) -> dict:
    """Extract knowledge using Gemini API (handles large PDFs via File API)."""
    import google.generativeai as genai

    genai.configure(api_key=GEMINI_API_KEY)

    file_size_mb = Path(pdf_path).stat().st_size / 1024 / 1024
    logger.info(f"Sending PDF to Gemini for analysis: {Path(pdf_path).name} ({file_size_mb:.1f} MB)")

    # Use Gemini File API for upload (supports large files)
    uploaded_file = genai.upload_file(pdf_path, mime_type="application/pdf")
    logger.info(f"Gemini file uploaded: {uploaded_file.name}")

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    model = genai.GenerativeModel(model_name)

    response = model.generate_content(
        [uploaded_file, EXTRACTION_PROMPT],
        generation_config=genai.GenerationConfig(max_output_tokens=8192),
    )

    raw = response.text.strip()
    return _parse_ai_response(raw)


def _extract_with_claude(pdf_path: str) -> dict:
    """Extract knowledge using Claude API (for smaller PDFs)."""
    import anthropic

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

    logger.info(f"Sending PDF to Claude for analysis: {Path(pdf_path).name} ({len(pdf_bytes) / 1024 / 1024:.1f} MB)")

    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=8192,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }
        ],
    )

    raw = response.content[0].text.strip()
    return _parse_ai_response(raw)


def _parse_ai_response(raw: str) -> dict:
    """Parse JSON from AI response, stripping code fences if present."""
    if raw.startswith("```"):
        first_newline = raw.index("\n")
        last_fence = raw.rfind("```")
        raw = raw[first_newline + 1:last_fence].strip()
    result = json.loads(raw)
    logger.info(f"Extracted {len(result.get('chapters', []))} chapters")
    return result


def extract_knowledge_from_pdf(pdf_path: str) -> dict:
    """Extract chapter structure + summaries from PDF.

    Uses Gemini for large files (>25MB) or when Gemini key is available,
    falls back to Claude for smaller files.

    Returns:
        {
            "title": "...",
            "summary": "全体要約 (300-500文字)",
            "chapters": [{"number": 1, "title": "...", "summary": "..."}, ...],
            "key_frameworks": [...],
            "applicable_to": "..."
        }
    """
    file_size_mb = Path(pdf_path).stat().st_size / 1024 / 1024

    # Large files: must use Gemini (Claude has ~30MB request limit)
    if file_size_mb > CLAUDE_MAX_FILE_SIZE_MB:
        if GEMINI_API_KEY:
            return _extract_with_gemini(pdf_path)
        else:
            raise ValueError(
                f"PDF is {file_size_mb:.1f}MB (Claude limit: {CLAUDE_MAX_FILE_SIZE_MB}MB). "
                f"Set GEMINI_API_KEY to process large PDFs."
            )

    # Normal files: try Gemini first (faster, larger context), fallback to Claude
    if GEMINI_API_KEY:
        try:
            return _extract_with_gemini(pdf_path)
        except Exception as e:
            logger.warning(f"Gemini extraction failed, falling back to Claude: {e}")
            if CLAUDE_API_KEY:
                return _extract_with_claude(pdf_path)
            raise

    if CLAUDE_API_KEY:
        return _extract_with_claude(pdf_path)

    raise RuntimeError("No AI API key configured (GEMINI_API_KEY or CLAUDE_API_KEY)")


def upload_and_index(pdf_path: str, title: str | None = None) -> dict:
    """Upload PDF to GCS and index it in knowledge_base sheet.

    Args:
        pdf_path: Local path to the PDF file
        title: Optional title override (auto-detected from PDF if not provided)

    Returns:
        The knowledge entry dict saved to Sheets.
    """
    pdf_path_obj = Path(pdf_path)
    if not pdf_path_obj.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    filename = pdf_path_obj.name
    doc_id = pdf_path_obj.stem  # e.g. "book-a_ai-bizdev"

    # Check if already indexed
    existing = get_all_rows("knowledge_base")
    for row in existing:
        if row.get("id") == doc_id:
            logger.info(f"PDF already indexed: {doc_id}, skipping")
            return row

    # 1. Upload to GCS
    gcs_path = upload_pdf_to_gcs(pdf_path)

    # 2. Extract knowledge via Claude
    knowledge = extract_knowledge_from_pdf(pdf_path)

    # 3. Save to Sheets
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    doc_title = title or knowledge.get("title", filename)
    summary = knowledge.get("summary", "")
    chapters_json = json.dumps(knowledge, ensure_ascii=False)

    row = [
        doc_id,
        filename,
        gcs_path,
        doc_title,
        summary,
        chapters_json,
        now,
    ]
    append_row("knowledge_base", row)
    logger.info(f"Knowledge indexed: {doc_title} ({len(knowledge.get('chapters', []))} chapters)")

    return {
        "id": doc_id,
        "filename": filename,
        "gcs_path": gcs_path,
        "title": doc_title,
        "summary": summary,
        "chapters_json": chapters_json,
        "uploaded_at": now,
    }


def get_knowledge_summary() -> str:
    """Get all knowledge summaries formatted for prompt injection.

    Returns:
        A formatted text string containing all book summaries and key frameworks.
    """
    try:
        rows = get_all_rows("knowledge_base")
    except Exception:
        return ""

    if not rows:
        return ""

    parts = []
    for row in rows:
        title = row.get("title", "")
        summary = row.get("summary", "")
        chapters_json = row.get("chapters_json", "")

        if not title or not summary:
            continue

        section = f"### {title}\n{summary}\n"

        # Add key frameworks if available
        if chapters_json:
            try:
                data = json.loads(chapters_json)
                frameworks = data.get("key_frameworks", [])
                applicable = data.get("applicable_to", "")
                if frameworks:
                    section += f"主要フレームワーク: {', '.join(frameworks)}\n"
                if applicable:
                    section += f"適用場面: {applicable}\n"
            except (json.JSONDecodeError, TypeError):
                pass

        parts.append(section)

    return "\n".join(parts)
