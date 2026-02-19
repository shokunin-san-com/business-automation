"""
0_idea_generator.py — Auto-generate business ideas using Claude API.

Reads target industries/keywords from Google Sheets settings,
generates ideas via Claude, saves as draft to Sheets,
writes pending_ideas.json for dashboard, and notifies Slack with approval buttons.
"""

import json
import sys
from pathlib import Path
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import TEMPLATES_DIR, GOOGLE_SHEETS_ID, DATA_DIR, get_logger
from utils.claude_client import generate_json
from utils.sheets_client import (
    get_all_rows,
    append_rows,
    get_spreadsheet,
)
from utils.slack_notifier import send_idea_approval_request
from utils.status_writer import update_status
from utils.pdf_knowledge import get_knowledge_summary
from utils.exploration_context import get_exploration_context
from utils.learning_engine import get_learning_context

logger = get_logger("idea_generator", "idea_generator.log")

jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

PENDING_IDEAS_FILE = DATA_DIR / "pending_ideas.json"


def _load_settings() -> dict:
    """Load key-value settings from the 'settings' sheet."""
    rows = get_all_rows("settings")
    return {r["key"]: r["value"] for r in rows}


def _make_slug(name: str) -> str:
    """Create a URL-safe slug from a Japanese business name."""
    import re

    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    slug = slug.strip("-")
    if not slug or not any(c.isalnum() for c in slug):
        slug = f"idea-{abs(hash(name)) % 100000:05d}"
    return slug


def generate_ideas() -> list[dict]:
    """Generate business ideas using Claude API."""
    settings = _load_settings()

    target_industries = settings.get("target_industries", "IT,エネルギー")
    trend_keywords = settings.get("trend_keywords", "AI,DX")
    num_ideas = int(settings.get("ideas_per_run", "3"))

    # Load knowledge base context (if available)
    knowledge_context = get_knowledge_summary()

    # Load exploration context (market research + competitor gaps)
    exploration_context = get_exploration_context()

    # Load learning context (AI insights + human directives)
    learning_context = get_learning_context(categories=["idea_generation"])

    template = jinja_env.get_template("idea_gen_prompt.j2")
    prompt = template.render(
        target_industries=target_industries,
        trend_keywords=trend_keywords,
        num_ideas=num_ideas,
        knowledge_context=knowledge_context,
        exploration_context=exploration_context,
        learning_context=learning_context,
    )

    logger.info(f"Generating {num_ideas} business ideas...")
    ideas = generate_json(
        prompt=prompt,
        system="あなたは日本市場に精通した事業戦略コンサルタントです。",
        max_tokens=4096,
        temperature=0.8,
    )

    if not isinstance(ideas, list):
        raise ValueError(f"Expected a list from Claude, got: {type(ideas)}")

    logger.info(f"Generated {len(ideas)} ideas")
    return ideas


def save_ideas_to_sheets(ideas: list[dict]) -> list[dict]:
    """Append generated ideas to business_ideas sheet as 'draft'.

    Returns list of saved ideas with their slugs/ids.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    saved_ideas = []

    for idea in ideas:
        slug = _make_slug(idea["name"])
        rows.append([
            slug,                              # id
            idea["name"],                      # name
            idea.get("category", ""),          # category
            idea.get("description", ""),       # description
            idea.get("target_audience", ""),   # target_audience
            "draft",                           # status
            "",                                # lp_url
            "auto",                            # source
            idea.get("market_size", ""),        # market_size
            idea.get("differentiator", ""),     # differentiator
            now,                               # created_at
        ])
        saved_ideas.append({
            "id": slug,
            "name": idea["name"],
            "category": idea.get("category", ""),
            "description": idea.get("description", ""),
            "target_audience": idea.get("target_audience", ""),
            "created_at": now,
        })

    append_rows("business_ideas", rows)
    logger.info(f"Saved {len(rows)} ideas to Google Sheets (status=draft)")
    return saved_ideas


def write_pending_ideas(ideas: list[dict]) -> None:
    """Write pending ideas to JSON file for dashboard display."""
    # Merge with any existing pending ideas
    existing = []
    if PENDING_IDEAS_FILE.exists():
        try:
            existing = json.loads(PENDING_IDEAS_FILE.read_text("utf-8"))
        except (json.JSONDecodeError, IOError):
            existing = []

    existing_ids = {i["id"] for i in existing}
    for idea in ideas:
        if idea["id"] not in existing_ids:
            existing.append(idea)

    PENDING_IDEAS_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), "utf-8")
    logger.info(f"Wrote {len(existing)} pending ideas to {PENDING_IDEAS_FILE}")


def notify_slack(ideas: list[dict]) -> None:
    """Send Slack notifications with approval buttons for each idea."""
    dashboard_url = "https://lp-app-pi.vercel.app/dashboard"

    for idea in ideas:
        send_idea_approval_request(idea, dashboard_url)

    logger.info(f"Sent {len(ideas)} Slack approval requests")


def main():
    logger.info("=== Idea generator start ===")
    update_status("0_idea_generator", "running", "事業案を生成中...")

    try:
        ideas = generate_ideas()
        saved_ideas = save_ideas_to_sheets(ideas)

        # Write pending ideas for dashboard
        write_pending_ideas(saved_ideas)

        # Send Slack notifications with approval buttons
        notify_slack(saved_ideas)

        count = len(saved_ideas)
        update_status("0_idea_generator", "success", f"{count}件生成", {"ideas_generated": count})
        logger.info("=== Idea generator complete ===")
    except Exception as e:
        update_status("0_idea_generator", "error", str(e))
        logger.error(f"Idea generator failed: {e}")
        raise


if __name__ == "__main__":
    main()
