"""
Index existing PDF books from bess-bizdev project into the knowledge base.

Run once to register:
  - book-a_ai-bizdev.pdf (AI事業開発フレームワーク)
  - book-b_business-creation.pdf (MIT 24ステップ事業創造法)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_logger
from utils.sheets_client import ensure_sheet_exists
from utils.pdf_knowledge import upload_and_index

logger = get_logger("index_pdfs", "index_pdfs.log")

# PDF files in the bess-bizdev project
BESS_REFERENCES = Path(__file__).resolve().parent.parent.parent / "bess-bizdev" / "references"

BOOKS = [
    {
        "path": BESS_REFERENCES / "book-a_ai-bizdev.pdf",
        "title": "AI駆動型事業開発フレームワーク",
    },
    {
        "path": BESS_REFERENCES / "book-b_business-creation.pdf",
        "title": "MIT 24ステップ事業創造法",
    },
]


def main():
    logger.info("=== PDF indexing start ===")

    # Ensure knowledge_base sheet exists
    ensure_sheet_exists("knowledge_base", [
        "id", "filename", "gcs_path", "title", "summary", "chapters_json", "uploaded_at",
    ])

    for book in BOOKS:
        pdf_path = book["path"]
        if not pdf_path.exists():
            logger.warning(f"PDF not found: {pdf_path}")
            continue

        logger.info(f"Indexing: {book['title']} ({pdf_path.name})")
        try:
            result = upload_and_index(str(pdf_path), title=book["title"])
            logger.info(f"Done: {result.get('title', '')} — {result.get('summary', '')[:80]}...")
        except Exception as e:
            logger.error(f"Failed to index {pdf_path.name}: {e}")

    logger.info("=== PDF indexing complete ===")


if __name__ == "__main__":
    main()
