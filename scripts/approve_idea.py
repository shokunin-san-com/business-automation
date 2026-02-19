"""
approve_idea.py — Helper to update a business idea status in Google Sheets.

Usage:
    python approve_idea.py <idea_id> <new_status> [approver]

Called from:
    - Next.js API /api/slack/approve
    - Slack Interactive Messages callback
"""

import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_logger
from utils.sheets_client import get_all_rows, find_row_index, update_cell

logger = get_logger("approve_idea", "approve_idea.log")


def approve(idea_id: str, new_status: str, approver: str = "system") -> bool:
    """Update the status of a business idea in Google Sheets.

    Args:
        idea_id: The slug/id of the business idea
        new_status: "active", "archived", "paused", etc.
        approver: Who performed the action (for logging)

    Returns:
        True if successful
    """
    logger.info(f"Updating idea '{idea_id}' -> status='{new_status}' by {approver}")

    row_idx = find_row_index("business_ideas", "id", idea_id)
    if not row_idx:
        logger.error(f"Idea '{idea_id}' not found in business_ideas sheet")
        return False

    # Column 6 = status (1-indexed: id, name, category, description, target_audience, status)
    update_cell("business_ideas", row_idx, 6, new_status)
    logger.info(f"Updated row {row_idx}: status -> {new_status}")

    return True


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python approve_idea.py <idea_id> <new_status> [approver]")
        sys.exit(1)

    idea_id = sys.argv[1]
    new_status = sys.argv[2]
    approver = sys.argv[3] if len(sys.argv) > 3 else "cli"

    success = approve(idea_id, new_status, approver)
    sys.exit(0 if success else 1)
