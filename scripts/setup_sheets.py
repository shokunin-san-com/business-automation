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
    # V1廃止: business_ideas, market_research, market_selection,
    #          competitor_analysis, ads_campaigns
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
    # ---------------------------------------------------------------
    # V2 新シート — 証拠ゲート・マイクロ市場・即決オファー
    # ---------------------------------------------------------------
    "gate_decision_log": [
        "run_id",
        "timestamp",
        "micro_market",
        "status",               # PASS / FAIL
        "missing_items",        # JSON: 未達条件リスト
        "evidence_urls",        # JSON: 取得済み証拠URL
        "payer",                # 支払者情報
        "blackout_hypothesis",  # 10社黒字化仮説
    ],
    "competitor_20_log": [
        "run_id",
        "market",
        "company_name",
        "url",
        "price_url",
        "case_url",
        "hire_url",
        "ad_url",
        "expo_url",
        "update_url",
    ],
    "offer_3_log": [
        "run_id",
        "offer_num",
        "payer",
        "offer_name",
        "deliverable",
        "time_to_value",
        "price",
        "replaces",
        "upsell",
        "headline",
        "pain_statement",
        "delivery_flow",
        "price_justification",
        "churn_risk",
        "monthly_300_calc",
    ],
    "lp_ready_log": [
        "run_id",
        "timestamp",
        "gate_ok",
        "competitor_ok",
        "offer_ok",
        "status",           # READY / BLOCKED
        "blocked_reason",
    ],
    "exploration_lane_log": [
        "run_id",
        "market",
        "adopted_reason",
        "deadline",
        "interview_count",
        "status",           # ACTIVE / EXPIRED / PASSED
    ],
    "micro_market_list": [
        "run_id",
        "market_id",
        "micro_market",
        "industry",
        "task",
        "role",
        "timing",
        "regulation",
        "intent_word",
        "a1q_status",
    ],
    "settings_snapshot": [
        "run_id",
        "timestamp",
        "snapshot_json",
    ],
    "ceo_reject_log": [
        "run_id",
        "type",             # market / offer
        "rejected_item",
        "reject_reason",
        "reviewed_by",
        "timestamp",
    ],
    "interview_log": [
        "run_id",
        "date",
        "interviewee_type",
        "top_pain",
        "current_alternative",
        "willingness_to_pay",
        "next_action",
    ],
    # ---------------------------------------------------------------
    # 下流指標 — 問い合わせ・案件・KPI
    # ---------------------------------------------------------------
    "inquiry_log": [
        "inquiry_id",
        "run_id",
        "business_id",
        "timestamp",
        "company_name",
        "contact_name",
        "contact_email",
        "message",
        "source_lp_url",
        "status",           # new / contacted / qualified / disqualified
        "qualified_at",
    ],
    "deal_pipeline": [
        "deal_id",
        "inquiry_id",
        "business_id",
        "run_id",
        "stage",            # inquiry / qualification / proposal / negotiation / won / lost
        "company_name",
        "deal_value",
        "created_at",
        "updated_at",
        "closed_at",
        "won_lost",
        "close_reason",
    ],
    "downstream_kpi": [
        "business_id",
        "date",
        "run_id",
        "total_inquiries",
        "qualified_inquiries",
        "proposals_sent",
        "deals_won",
        "deals_lost",
        "total_deal_value",
        "test_conversion_rate",
        "target_customer_rate",
        "deal_rate",
    ],
    # ---------------------------------------------------------------
    # 拡張層 — 勝ちパターン検出・拡張アクション
    # ---------------------------------------------------------------
    "winning_patterns": [
        "pattern_id",
        "run_id",
        "business_id",
        "micro_market",
        "offer_name",
        "payer",
        "lp_url",
        "detection_date",
        "pattern_type",         # quick_win / steady_growth / high_potential
        "metrics_json",
        "sop_json",
        "budget_recommendation_json",
        "status",               # detected / validated / scaling / saturated / archived
        "scaling_stage",        # initial / testing / scaling / mature
    ],
    "expansion_log": [
        "log_id",
        "pattern_id",
        "business_id",
        "action_type",
        "action_detail",
        "executed_at",
        "result",
    ],
    # ---------------------------------------------------------------
    # SNS投稿キュー + ブログ記事
    # ---------------------------------------------------------------
    "sns_queue": [
        "queue_id",
        "business_id",
        "platform",
        "post_text",
        "category",
        "status",           # queued / posted / failed / skipped
        "scheduled_at",
        "posted_at",
        "post_url",
        "error_detail",
    ],
    "blog_articles": [
        "article_id",
        "business_id",
        "title",
        "slug",
        "body_html",
        "excerpt",
        "category",
        "tags",
        "meta_description",
        "og_title",
        "og_description",
        "status",           # draft / published
        "published_at",
        "generated_at",
    ],
    # ---------------------------------------------------------------
    # v2 追加シート — コスト追跡・メール・需要検証・Validation
    # ---------------------------------------------------------------
    "cost_tracking": [
        "run_id",
        "timestamp",
        "phase",
        "api_name",
        "input_tokens",
        "output_tokens",
        "used_search",
        "cost_jpy",
        "note",
    ],
    "demand_verification_log": [
        "run_id",
        "group_id",
        "keywords",
        "suggest_result",
        "gemini_grounding_result",
        "sns_pain_result",
        "verdict",          # CONFIRMED / WEAK / NOT_FOUND
        "detail_json",
        "timestamp",
    ],
    "email_targets": [
        "run_id",
        "business_id",
        "company_name",
        "email",
        "source_url",
        "region",
        "industry",
        "status",           # new / sent / replied / bounced
        "collected_at",
    ],
    "mail_approval": [
        "run_id",
        "business_id",
        "offer_name",
        "target_company",
        "target_email",
        "subject",
        "body_text",
        "ceo_decision",     # pending / approved / rejected
        "decided_at",
        "created_at",
    ],
    "mail_sent_log": [
        "run_id",
        "business_id",
        "target_email",
        "subject",
        "sent_at",
        "gmail_message_id",
        "status",           # sent / failed / bounced
        "error_detail",
    ],
    "validation_score_log": [
        "run_id",
        "business_id",
        "evaluation_date",
        "emails_sent",
        "replies_received",
        "inquiries_received",
        "rank",             # A / B / C / D
        "action",           # expand / extend / ceo_review / stop
        "detail_json",
    ],
    # ---------------------------------------------------------------
    # v2 探索エンジン — 型・コンボ・検索ボリューム
    # ---------------------------------------------------------------
    "business_model_types": [
        "run_id",
        "type_id",
        "axis",
        "prompt_id",
        "type_name",
        "description",
        "revenue_model",
        "example",
        "merged_from",
        "review_pass",
        "exists_check",
        "strength_fit",
        "generated_at",
    ],
    "business_combos": [
        "run_id",
        "combo_id",
        "type_id",
        "business_name",
        "target",
        "deliverable",
        "price_model",
        "monthly_300_path",
        "why_pay",
        "who_pays_now",
        "switching_reason",
        "generated_at",
    ],
    "search_volume_log": [
        "run_id",
        "keyword",
        "monthly_volume",
        "source",
        "checked_at",
    ],
    "competitor_pricing_log": [
        "run_id",
        "market",
        "company_name",
        "plan_name",
        "price",
        "price_source_url",
    ],
    "priority_score_log": [
        "run_id",
        "business_id",
        "combo_id",
        "score",
        "detail_json",
        "scored_at",
    ],
}

# Default settings to seed
DEFAULT_SETTINGS = [
    ["target_industries", "エネルギー,IT,建設,製造", "事業案生成で探索する業界カテゴリ"],
    ["trend_keywords", "BESS,AI,DX,脱炭素,SaaS", "事業案生成で参照するトレンドキーワード"],
    ["ideas_per_run", "3", "1回の実行で生成する事業案の数"],
    ["idea_direction_notes", "建設業界の実務課題を軸に、許認可(有料職業紹介/特定技能/M&A登録支援)活用型・受託/BPO/エージェント型で展開。AI/SaaSは禁止。具体的納品物(レポート/書類作成/マッチング/代行)で即決オファーを設計。", "事業案生成の方向性メモ"],
    ["sns_posts_per_day", "2", "1日あたりのSNS投稿数"],
    ["form_sales_per_day", "5", "1日あたりのフォーム営業数"],
    ["competitors_per_market", "20", "各選定市場で分析する競合数（Gemini grounding）"],
    # exploration_scoring_weights — v2で廃止（スコアリング禁止）
    ["market_direction_notes", "", "市場探索・選定の方向性メモ（自由記述）"],
    ["use_ceo_profile", "false", "trueでCEO経歴スコアリング有効"],
    ["ceo_profile_json", "岡部。M&Aフルサイクル経験（ソーシング→DD→バリュエーション→PMI→売却）。建設・インフラの設備設計〜施工管理の実務あり。海外ビジネス（ベトナム進出、英語交渉、輸入実務）。再生可能エネルギー（系統用蓄電池の市場調査・用地調査）。有料職業紹介事業の許認可保有、特定技能・登録支援機関の知見。複数企業の創業→売却、PMI完遂の実績。上場企業の経営企画・IR経験。得意業界: 建設、エネルギー、M&A、人材紹介、インフラ、製造。モチベーション: 海外案件、大規模エネルギー事業、M&A。資格: 第二種電気工事士、有料職業紹介事業、M&A登録支援機関", "CEO経歴データ（自由記述）"],
    ["kill_criteria_days", "14", "損切り判定の評価期間（日数）"],
    ["kill_criteria_min_cv", "1", "期間内の最低CV数。これ未満で撤退候補"],
    ["kill_criteria_min_score", "15", "期間平均スコア最低ライン"],
    ["kill_criteria_enabled", "true", "損切り判定の有効/無効"],
    ["monthly_ad_budget", "100000", "月間広告予算（円）"],
    ["ads_daily_budget", "3000", "広告自動出稿のデフォルト日次予算（円）"],
    ["sender_name", "岡部", "フォーム営業の送信者名"],
    ["sender_email", "inoue@shokunin-san.com", "フォーム営業の返信先メールアドレス"],
    ["sender_company", "MarketProbe Project", "フォーム営業で使用する会社名"],
    # orchestrator_auto_approve / auto_approve_n / min_score_threshold — v2で廃止（ゲート制に移行）
    ["pipeline_improvement_log", "", "自己反省の改善提案・リスク・次回アクション蓄積（最新5件）"],
    # 拡張層設定
    ["expansion_min_inquiries", "5", "拡張判定に必要な最低問い合わせ数"],
    ["expansion_min_deal_rate", "0.1", "拡張判定に必要な最低成約率"],
    ["expansion_min_days", "14", "拡張判定に必要な最低運用日数"],
    # v2 追加設定
    ["gmail_sender_email", "inoue@shokunin-san.com", "Gmail API送信元アドレス"],
    ["mail_daily_limit", "50", "1日あたりのメール送信上限"],
    ["cost_warn_jpy", "25000", "月間API費用の警告閾値（円）"],
    ["cost_hard_stop_jpy", "30000", "月間API費用の強制停止閾値（円）"],
    ["max_sv_combos", "50", "需要検証に進めるコンボ最大数"],
    ["max_competitor_combos", "5", "競合分析に進めるコンボ最大数"],
    ["validation_period_days", "14", "Validation評価期間（日数）"],
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
