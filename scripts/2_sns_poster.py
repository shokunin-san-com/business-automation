"""
2_sns_poster.py — Auto-post to X (Twitter) and LinkedIn for active business ideas.

Risk scoring flow:
  score <= 30 → AUTO post
  score 31-70 → Queue for human review (Slack notification)
  score > 70  → BLOCK (alert human)
"""


from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import TEMPLATES_DIR, get_logger
from utils.claude_client import generate_json
from utils.sheets_client import get_rows_by_status, get_all_rows, append_row
from utils.twitter_client import post_tweet
from utils.linkedin_client import post_text as post_linkedin
from utils.slack_notifier import send_message as slack_notify
from utils.status_writer import update_status
from utils.risk_scorer import evaluate as evaluate_risk
from utils.learning_engine import get_learning_context

logger = get_logger("sns_poster", "sns_poster.log")

jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

LP_BASE_URL = "https://lp-app-pi.vercel.app"


def _get_posted_keys() -> set[str]:
    """Return set of (business_id, platform) already posted today."""
    today = datetime.now().strftime("%Y-%m-%d")
    rows = get_all_rows("sns_posts")
    return {
        (r["business_id"], r["platform"])
        for r in rows
        if str(r.get("posted_at", "")).startswith(today)
    }


def _generate_posts(idea: dict, platform: str, learning_context: str = "") -> list[str]:
    """Generate SNS posts for a business idea and platform."""
    lp_url = f"{LP_BASE_URL}/lp/{quote(idea['id'], safe='')}"
    template = jinja_env.get_template("sns_prompt.j2")
    prompt = template.render(
        platform=platform,
        name=idea["name"],
        description=idea.get("description", ""),
        target_audience=idea.get("target_audience", ""),
        lp_url=lp_url,
        num_posts=1,
        learning_context=learning_context,
    )

    # Try with sufficient tokens; retry once with higher limit on parse failure
    for attempt, tokens in enumerate([4096, 8192], 1):
        posts = generate_json(
            prompt=prompt,
            system="あなたは日本語SNSマーケティングの専門家です。JSON配列を返してください。",
            max_tokens=tokens,
            temperature=0.8,
        )
        texts = [p["text"] for p in posts if isinstance(p, dict) and "text" in p]
        if texts:
            return texts
        logger.warning(f"Attempt {attempt}: generate_json returned no valid posts (tokens={tokens})")

    return []


def _record_post(
    business_id: str, platform: str, text: str, url: str, risk_decision: str = "auto"
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    append_row("sns_posts", [business_id, platform, text, url, now])


def _try_post(
    idea: dict, platform: str, text: str
) -> tuple[str, str]:
    """Evaluate risk and post if safe. Returns (status, url)."""
    risk = evaluate_risk(
        text=text,
        platform=platform,
        context=f"SNS post for {idea['name']}",
        use_ai=True,
    )

    if risk.decision == "auto":
        logger.info(f"Risk score {risk.score} → AUTO posting to {platform}")
        if platform == "twitter":
            result = post_tweet(text)
        else:
            result = post_linkedin(text)

        if result is None:
            logger.error(f"Failed to post to {platform} for {idea['name']}")
            slack_notify(
                f":x: *{platform}投稿に失敗* しました\n"
                f"事業案: {idea['name']}\n"
                f"API投稿エラー（403の場合: 月間投稿上限 or 重複コンテンツの可能性）"
            )
            return "error", ""

        url = result.get("url", "") or result.get("id", "")
        return "posted", url

    elif risk.decision == "review":
        logger.info(f"Risk score {risk.score} → REVIEW required for {platform}")
        slack_notify(
            f":warning: SNS投稿が *要確認* です（リスクスコア: {risk.score}）\n"
            f"プラットフォーム: {platform}\n"
            f"事業案: {idea['name']}\n"
            f"理由: {risk.detail}\n"
            f"```{text[:200]}...```\n"
            f"ダッシュボードで確認してください。"
        )
        return "pending_review", ""

    else:  # block
        logger.warning(f"Risk score {risk.score} → BLOCKED for {platform}")
        slack_notify(
            f":no_entry: SNS投稿が *ブロック* されました（リスクスコア: {risk.score}）\n"
            f"プラットフォーム: {platform}\n"
            f"事業案: {idea['name']}\n"
            f"理由: {risk.detail}\n"
            f"内容を見直してください。"
        )
        return "blocked", ""


def main():
    logger.info("=== SNS poster start ===")
    update_status("2_sns_poster", "running", "SNS投稿準備中...")

    try:
        active_ideas = get_rows_by_status("business_ideas", "active")
        if not active_ideas:
            logger.info("No active ideas. Exiting.")
            update_status("2_sns_poster", "success", "対象なし", {"posts": 0})
            return

        posted_keys = _get_posted_keys()
        learning_context = get_learning_context(categories=["sns_strategy"])
        total_posted = 0
        total_reviewed = 0
        total_blocked = 0
        total_errors = 0

        for idea in active_ideas:
            bid = idea["id"]

            for platform in ["twitter", "linkedin"]:
                if (bid, platform) in posted_keys:
                    continue

                update_status("2_sns_poster", "running", f"{platform}投稿生成中: {idea['name']}")
                logger.info(f"Generating {platform} posts for {bid}")
                texts = _generate_posts(idea, platform, learning_context=learning_context)
                if not texts:
                    continue

                text = texts[0]
                status, url = _try_post(idea, platform, text)
                _record_post(bid, platform, text, url, status)

                if status == "posted":
                    total_posted += 1
                elif status == "pending_review":
                    total_reviewed += 1
                elif status == "blocked":
                    total_blocked += 1
                elif status == "error":
                    total_errors += 1

        summary_parts = []
        if total_posted:
            summary_parts.append(f"自動投稿 {total_posted}件")
        if total_reviewed:
            summary_parts.append(f"要確認 {total_reviewed}件")
        if total_blocked:
            summary_parts.append(f"ブロック {total_blocked}件")
        if total_errors:
            summary_parts.append(f"エラー {total_errors}件")

        if total_posted or total_errors:
            slack_notify(f":mega: SNS投稿: {' / '.join(summary_parts)}")

        final_status = "success" if total_errors == 0 else "error"
        update_status("2_sns_poster", final_status, " / ".join(summary_parts) or "対象なし", {
            "posted": total_posted,
            "reviewed": total_reviewed,
            "blocked": total_blocked,
            "errors": total_errors,
        })
        logger.info(f"=== SNS poster complete: posted={total_posted}, review={total_reviewed}, blocked={total_blocked}, errors={total_errors} ===")
    except Exception as e:
        update_status("2_sns_poster", "error", str(e))
        logger.error(f"SNS poster failed: {e}")
        raise


if __name__ == "__main__":
    main()
