"""
Google Sheets initial setup — create all required sheets with headers.
Run once to initialize the spreadsheet structure.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_logger
from utils.sheets_client import ensure_sheet_exists

logger = get_logger("setup_sheets", "setup_sheets.log")

SHEETS = {
    "business_ideas": [
        "id",
        "name",
        "category",
        "description",
        "target_audience",
        "status",
        "lp_url",
        "source",
        "market_size",
        "differentiator",
        "created_at",
    ],
    "lp_content": [
        "business_id",
        "headline",
        "subheadline",
        "sections_json",
        "cta_text",
        "meta_description",
        "og_title",
        "og_description",
        "generated_at",
    ],
    "sns_posts": [
        "business_id",
        "platform",
        "post_text",
        "post_url",
        "posted_at",
    ],
    "form_sales_targets": [
        "business_id",
        "company_name",
        "url",
        "form_url",
        "industry",
        "region",
        "message",
        "status",
        "contacted_at",
        "response",
    ],
    "analytics": [
        "business_id",
        "date",
        "pageviews",
        "sessions",
        "bounce_rate",
        "conversions",
        "avg_time",
    ],
    "improvement_suggestions": [
        "business_id",
        "suggested_at",
        "suggestion_text",
        "priority",
        "status",
    ],
    "settings": [
        "key",
        "value",
        "description",
    ],
    "pipeline_status": [
        "script_name",
        "status",
        "detail",
        "metrics_json",
        "timestamp",
    ],
    "execution_logs": [
        "timestamp",
        "job_name",
        "trigger",
        "status",
        "detail",
        "executed_by",
    ],
    "knowledge_base": [
        "id",
        "filename",
        "gcs_path",
        "title",
        "summary",
        "chapters_json",
        "uploaded_at",
    ],
    "market_research": [
        "id",
        "market_name",
        "industry",
        "market_size_tam",
        "market_size_sam",
        "growth_rate",
        "pest_political",
        "pest_economic",
        "pest_social",
        "pest_technological",
        "industry_structure",
        "key_players",
        "customer_pain_points",
        "entry_barriers",
        "regulations",
        "data_sources",
        "confidence_score",
        "status",
        "research_batch_id",
        "created_at",
    ],
    "market_selection": [
        "id",
        "market_research_id",
        "market_name",
        "score_distortion_depth",
        "score_entry_barrier",
        "score_bpo_feasibility",
        "score_growth",
        "score_capability_fit",
        "total_score",
        "rank",
        "pest_summary",
        "five_forces_summary",
        "rationale",
        "recommended_entry_angle",
        "status",
        "reviewed_by",
        "batch_id",
        "created_at",
    ],
    "competitor_analysis": [
        "id",
        "market_selection_id",
        "market_name",
        "competitor_name",
        "competitor_url",
        "competitor_type",
        "product_service",
        "pricing_model",
        "target_segment",
        "strengths",
        "weaknesses",
        "market_share_estimate",
        "differentiation",
        "gap_opportunities",
        "created_at",
    ],
    "performance_log": [
        "id",
        "business_id",
        "date",
        "lp_pageviews",
        "lp_sessions",
        "lp_bounce_rate",
        "lp_avg_time",
        "lp_conversions",
        "sns_posts_count",
        "form_submissions",
        "form_responses",
        "performance_score",
        "created_at",
    ],
    "learning_memory": [
        "id",
        "type",
        "source",
        "category",
        "content",
        "context_json",
        "confidence",
        "priority",
        "status",
        "applied_count",
        "created_at",
        "expires_at",
    ],
}

# Default settings to seed
DEFAULT_SETTINGS = [
    ["target_industries", "エネルギー,IT,建設,製造", "事業案生成で探索する業界カテゴリ"],
    ["trend_keywords", "BESS,AI,DX,脱炭素,SaaS", "事業案生成で参照するトレンドキーワード"],
    ["ideas_per_run", "3", "1回の実行で生成する事業案の数"],
    ["sns_posts_per_day", "2", "1日あたりのSNS投稿数"],
    ["form_sales_per_day", "5", "1日あたりのフォーム営業数"],
    ["exploration_markets", "エネルギー,IT,建設,製造,物流", "探索フェーズで調査する市場カテゴリ"],
    ["exploration_segments_per_market", "3", "各市場で調査するセグメント数"],
    ["selection_top_n", "3", "市場選定で承認候補にする上位市場数"],
    ["competitors_per_market", "5", "各選定市場で分析する競合数"],
    ["exploration_scoring_weights", '{"distortion":3,"barrier":2,"bpo":2,"growth":1.5,"capability":1.5}', "市場選定の5軸重み設定"],
]


def main():
    logger.info("=== Google Sheets setup start ===")

    for sheet_name, headers in SHEETS.items():
        ensure_sheet_exists(sheet_name, headers)

    # Seed default settings (add missing keys without overwriting existing)
    from utils.sheets_client import get_all_rows, append_rows

    existing = get_all_rows("settings")
    existing_keys = {r.get("key", "") for r in existing}
    new_settings = [s for s in DEFAULT_SETTINGS if s[0] not in existing_keys]

    if new_settings:
        append_rows("settings", new_settings)
        logger.info(f"Added {len(new_settings)} new settings: {[s[0] for s in new_settings]}")
    else:
        logger.info("All settings already exist, skipping seed")

    logger.info("=== Google Sheets setup complete ===")


if __name__ == "__main__":
    main()
