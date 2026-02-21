#!/usr/bin/env python3
"""
Upload local files to knowledge base.

Usage:
  python3 scripts/upload_knowledge.py references/my-book.pdf
  python3 scripts/upload_knowledge.py references/my-book.pdf --title "カスタムタイトル"
  python3 scripts/upload_knowledge.py references/*.pdf

Supports: PDF, CSV, Excel (.xlsx/.xls), Images (.png/.jpg/.webp)

Large PDFs are handled by:
1. Uploading to GCS for permanent storage
2. Splitting into chunks if needed for AI extraction
3. Saving metadata + summaries to knowledge_base sheet
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_logger
from utils.pdf_knowledge import upload_and_index

logger = get_logger("upload_knowledge")

SUPPORTED_EXTENSIONS = {".pdf", ".csv", ".xlsx", ".xls", ".png", ".jpg", ".jpeg", ".webp"}


def main():
    parser = argparse.ArgumentParser(description="Upload files to knowledge base")
    parser.add_argument("files", nargs="+", help="File path(s) to upload")
    parser.add_argument("--title", help="Custom title (only for single file)")
    args = parser.parse_args()

    files = []
    for f in args.files:
        p = Path(f)
        if not p.exists():
            logger.error(f"File not found: {f}")
            continue
        if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
            logger.error(f"Unsupported file type: {p.suffix} ({f})")
            logger.info(f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
            continue
        files.append(p)

    if not files:
        logger.error("No valid files to upload")
        sys.exit(1)

    if args.title and len(files) > 1:
        logger.warning("--title is ignored when uploading multiple files")

    for filepath in files:
        try:
            logger.info(f"Processing: {filepath.name} ({filepath.stat().st_size / 1024 / 1024:.1f} MB)")
            title = args.title if len(files) == 1 else None
            result = upload_and_index(str(filepath), title=title)
            logger.info(f"Done: {result['title']}")
            logger.info(f"  Summary: {result['summary'][:100]}...")
        except Exception as e:
            logger.error(f"Failed to process {filepath.name}: {e}")
            continue

    logger.info("All files processed")


if __name__ == "__main__":
    main()
