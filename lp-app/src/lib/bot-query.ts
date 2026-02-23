/**
 * Shared bot query/directive logic — used by Slack and Google Chat handlers.
 */
import crypto from "crypto";
import { getAllRows, appendRows, ensureSheetExists, updateCell, getSheetUrls } from "@/lib/sheets";
import { getAccessToken, GCP_PROJECT, GCP_REGION, JOB_MAP } from "@/lib/gcp-auth";
import { GoogleGenerativeAI } from "@google/generative-ai";

const LEARNING_HEADERS = [
  "id", "type", "source", "category", "content",
  "context_json", "confidence", "priority", "status",
  "applied_count", "created_at", "expires_at",
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generateId(): string {
  const hex = Array.from(crypto.getRandomValues(new Uint8Array(4)))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return `dir_${hex}`;
}

/** Classify the message into a directive category using keyword matching. */
export function classifyCategory(text: string): string {
  const lower = text.toLowerCase();
  if (/lp|ランディング|ページ|cta|ヘッドライン|コンバージョン/.test(lower))
    return "lp_optimization";
  if (/sns|ツイート|投稿|x(\s|$)|twitter|ハッシュタグ/.test(lower))
    return "sns_strategy";
  if (/フォーム|営業|メール|dm|メッセージ/.test(lower))
    return "form_sales";
  if (/事業案|アイデア|市場|リサーチ/.test(lower))
    return "idea_generation";
  return "general";
}

/** Detect if the message is a question/query (vs a directive/instruction). */
export function isQuery(text: string): boolean {
  const lower = text.toLowerCase();
  if (/教えて|知りたい|どう|どの|いくつ|何件|確認|状況|成果|レポート|報告|見せて|まとめ/.test(lower)) return true;
  if (/\?|？/.test(lower)) return true;
  if (/提案して|提案|分析して|出して|表示して|一覧|リスト|サマリー|概要|戦略|方針/.test(lower)) return true;
  if (/パイプライン|ステータス|最新|直近|今日|今週|結果/.test(lower)) return true;
  if (/今後|改善|課題|傾向|推移|比較/.test(lower)) return true;
  if (/フロー|条件|仕組み|手順|説明|内容|キーポイント|ポイント|整理/.test(lower)) return true;
  return false;
}

// ---------------------------------------------------------------------------
// Execution command detection & handler
// ---------------------------------------------------------------------------

/**
 * Action verbs that explicitly mean "run this job".
 * IMPORTANT: `して` alone is too ambiguous — it matches `出して`, `まとめて`, etc.
 * Only match `して` when preceded by `を` (e.g., `市場調査をして`), not as part of
 * compound verbs like `出して`, `教えて`, `見せて`.
 */
const ACTION_VERBS = "実行|をして|やって|走らせ|開始|回して|かけて|お願い|頼む|頼み";

/** Map of keyword patterns to script IDs for execution commands */
const EXEC_PATTERNS: { pattern: RegExp; scriptId: string; label: string }[] = [
  { pattern: new RegExp(`市場(調査|リサーチ).*(${ACTION_VERBS})`), scriptId: "A_market_research", label: "市場調査" },
  { pattern: new RegExp(`(${ACTION_VERBS}).*市場(調査|リサーチ)`), scriptId: "A_market_research", label: "市場調査" },
  { pattern: new RegExp(`市場選定.*(${ACTION_VERBS})`), scriptId: "B_market_selection", label: "市場選定" },
  { pattern: new RegExp(`(${ACTION_VERBS}).*市場選定`), scriptId: "B_market_selection", label: "市場選定" },
  { pattern: new RegExp(`競合(調査|分析).*(${ACTION_VERBS})`), scriptId: "C_competitor_analysis", label: "競合調査" },
  { pattern: new RegExp(`(${ACTION_VERBS}).*競合(調査|分析)`), scriptId: "C_competitor_analysis", label: "競合調査" },
  { pattern: new RegExp(`事業案.*(生成|作って|${ACTION_VERBS})`), scriptId: "0_idea_generator", label: "事業案生成" },
  { pattern: new RegExp(`(${ACTION_VERBS}).*事業案`), scriptId: "0_idea_generator", label: "事業案生成" },
  { pattern: new RegExp(`lp.*(生成|作って|${ACTION_VERBS})`), scriptId: "1_lp_generator", label: "LP生成" },
  { pattern: new RegExp(`(${ACTION_VERBS}).*lp`), scriptId: "1_lp_generator", label: "LP生成" },
  { pattern: new RegExp(`sns.*(投稿|${ACTION_VERBS})`), scriptId: "2_sns_poster", label: "SNS投稿" },
  { pattern: new RegExp(`(${ACTION_VERBS}).*sns`), scriptId: "2_sns_poster", label: "SNS投稿" },
  { pattern: new RegExp(`フォーム(営業|送信).*(${ACTION_VERBS})`), scriptId: "3_form_sales", label: "フォーム営業" },
  { pattern: new RegExp(`(${ACTION_VERBS}).*フォーム(営業|送信)`), scriptId: "3_form_sales", label: "フォーム営業" },
  { pattern: new RegExp(`(分析|アナリティクス).*(${ACTION_VERBS})`), scriptId: "4_analytics_reporter", label: "分析・改善" },
  { pattern: new RegExp(`(${ACTION_VERBS}).*(分析|アナリティクス)`), scriptId: "4_analytics_reporter", label: "分析・改善" },
  { pattern: new RegExp(`(slack|レポート).*(${ACTION_VERBS}|送|配信)`), scriptId: "5_slack_reporter", label: "Slackレポート" },
  { pattern: new RegExp(`広告(監視|モニター).*(${ACTION_VERBS})`), scriptId: "6_ads_monitor", label: "広告監視" },
  { pattern: new RegExp(`学習.*(${ACTION_VERBS}|回)`), scriptId: "7_learning_engine", label: "学習エンジン" },
  { pattern: new RegExp(`(${ACTION_VERBS}).*学習`), scriptId: "7_learning_engine", label: "学習エンジン" },
  { pattern: new RegExp(`(自律|abc0|全自動|フル).*(パイプライン|実行).*(${ACTION_VERBS})`), scriptId: "orchestrate_abc0", label: "自律型パイプライン" },
  { pattern: new RegExp(`(${ACTION_VERBS}).*(自律|abc0|全自動|フル).*(パイプライン|実行)`), scriptId: "orchestrate_abc0", label: "自律型パイプライン" },
  { pattern: new RegExp(`パイプライン.*(全部|フル|一気に|まとめて|通して).*(${ACTION_VERBS})`), scriptId: "orchestrate_abc0", label: "自律型パイプライン" },
  { pattern: new RegExp(`(${ACTION_VERBS}).*(一気通貫|エンドツーエンド|e2e)`), scriptId: "orchestrate_abc0", label: "自律型パイプライン" },
  // V2 pipeline
  { pattern: /v2.*パイプライン|新.*パイプライン|v2.*実行/, scriptId: "orchestrate_v2", label: "V2パイプライン" },
  { pattern: new RegExp(`(${ACTION_VERBS}).*v2`), scriptId: "orchestrate_v2", label: "V2パイプライン" },
  { pattern: /ゲート.*パイプライン|証拠.*パイプライン/, scriptId: "orchestrate_v2", label: "V2パイプライン" },
];

/** Detect if the message is an execution command.
 *  Returns null if the message looks like a question/query — even if it
 *  contains job-related keywords like "市場調査".
 */
export function isExecutionCommand(text: string): { scriptId: string; label: string } | null {
  // If the message reads like a question, never treat it as an execution command.
  // e.g. "市場調査のフローを出して" is a question, NOT "run market research".
  if (isQuery(text)) return null;

  const lower = text.toLowerCase();
  for (const { pattern, scriptId, label } of EXEC_PATTERNS) {
    if (pattern.test(lower)) return { scriptId, label };
  }
  return null;
}

/** Execute a Cloud Run Job and return a status message */
export async function handleExecutionCommand(
  scriptId: string,
  label: string,
  triggeredBy: string,
): Promise<string> {
  const entry = JOB_MAP[scriptId];
  if (!entry) {
    return `⚠️ 「${label}」に対応するジョブが見つかりません。`;
  }

  try {
    const token = await getAccessToken();
    const url = `https://${GCP_REGION}-run.googleapis.com/v2/projects/${GCP_PROJECT}/locations/${GCP_REGION}/jobs/${entry.jobId}:run`;

    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
    });

    if (!res.ok) {
      const errText = await res.text();
      console.error(`[bot-query] Cloud Run execute error for ${entry.jobId}:`, errText);
      return `⚠️ 「${label}」の実行に失敗しました（${res.status}）。ダッシュボードから再試行してください。`;
    }

    const result = await res.json();
    const executionName = result.metadata?.name || result.name || "";

    // Log execution
    try {
      await ensureSheetExists("execution_logs", [
        "timestamp", "job_name", "trigger", "status", "detail", "executed_by",
      ]);
      await appendRows("execution_logs", [[
        new Date().toISOString(),
        scriptId,
        "chat",
        "triggered",
        `Execution: ${executionName}`,
        triggeredBy,
      ]]);
    } catch { /* best-effort */ }

    return (
      `🚀 *${label}* を実行開始しました！\n` +
      `> ジョブ: \`${entry.jobId}\`\n` +
      `完了までしばらくお待ちください。結果はダッシュボードで確認できます。`
    );
  } catch (err) {
    console.error(`[bot-query] Error executing ${scriptId}:`, err);
    return `⚠️ 「${label}」の実行中にエラーが発生しました。`;
  }
}

// ---------------------------------------------------------------------------
// Settings auto-update from AI response
// ---------------------------------------------------------------------------

const UPDATABLE_SETTINGS = new Set([
  "target_industries", "trend_keywords", "exploration_markets",
  "ideas_per_run", "idea_direction_notes", "market_direction_notes",
  "orchestrator_auto_approve", "orchestrator_min_score_threshold",
]);

async function applySettingsUpdate(text: string): Promise<string[]> {
  const match = text.match(/\[SETTINGS_UPDATE\]\s*([\s\S]*?)\s*\[\/SETTINGS_UPDATE\]/);
  if (!match) return [];

  try {
    const updates = JSON.parse(match[1].trim()) as Record<string, string>;
    const applied: string[] = [];

    for (const [key, value] of Object.entries(updates)) {
      if (!UPDATABLE_SETTINGS.has(key)) {
        console.warn(`[bot-query] Skipping non-updatable setting: ${key}`);
        continue;
      }
      await updateCell("settings", "key", key, "value", String(value));
      applied.push(key);
      console.log(`[bot-query] Settings updated: ${key} = ${String(value).substring(0, 50)}...`);
    }

    return applied;
  } catch (err) {
    console.error("[bot-query] Failed to parse/apply SETTINGS_UPDATE:", err);
    return [];
  }
}

/** Strip SETTINGS_UPDATE tags from the AI response before sending to user */
function stripSettingsTag(text: string): string {
  return text.replace(/\[SETTINGS_UPDATE\][\s\S]*?\[\/SETTINGS_UPDATE\]/g, "").trim();
}

/** Get current settings summary for prompt injection */
async function getCurrentSettings(): Promise<string> {
  try {
    const rows = await getAllRows("settings");
    const settingsKeys = [
      "target_industries", "trend_keywords", "exploration_markets",
      "ideas_per_run", "idea_direction_notes", "market_direction_notes",
      "exploration_segments_per_market", "selection_top_n", "competitors_per_market",
      "pipeline_improvement_log",
    ];
    const parts: string[] = [];
    for (const key of settingsKeys) {
      const row = rows.find((r) => r.key === key);
      if (row?.value) {
        parts.push(`${key}: ${row.value}`);
      }
    }
    return parts.length > 0 ? parts.join("\n") : "";
  } catch {
    return "";
  }
}

// ---------------------------------------------------------------------------
// Data query handlers
// ---------------------------------------------------------------------------

export async function handleDataQuery(message: string): Promise<string> {
  const lower = message.toLowerCase();

  // System explanation — "何これ", "わかるように教えて", "使い方", "ヘルプ" etc.
  if (/なんの(チャット|アプリ|ボット|システム)|何これ|使い方|ヘルプ|help|わかるように|説明して|どういう/.test(lower)) {
    return getSystemExplanation();
  }

  // Collect relevant data context, then let AI generate a natural response
  const dataContext = await gatherDataContext(lower);
  const aiReply = await generateAIResponse(message, dataContext);
  if (aiReply) return aiReply;

  // Fallback: template-based responses if AI is unavailable
  if (/戦略|提案|方針|今後|改善|課題/.test(lower)) {
    return await getStrategySummary();
  }
  if (/lp|成果|pv|ページビュー|コンバージョン|cvr|分析|アクセス/.test(lower)) {
    return await getLPPerformanceSummary();
  }
  if (/パイプライン|ステータス|状況|エラー|実行/.test(lower)) {
    return await getPipelineStatus();
  }
  if (/sns|投稿|ツイート/.test(lower)) {
    return await getSNSSummary();
  }
  if (/事業案|アイデア|市場/.test(lower)) {
    return await getIdeasSummary();
  }
  return await getOverview();
}

/** Gather relevant data based on message keywords */
async function gatherDataContext(lower: string): Promise<string> {
  const parts: string[] = [];

  try {
    // Always include basic overview
    const [ideas, status, analytics, snsPosts, marketSelection] = await Promise.all([
      getAllRows("business_ideas").catch(() => []),
      getAllRows("pipeline_status").catch(() => []),
      getAllRows("analytics").catch(() => []),
      getAllRows("sns_posts").catch(() => []),
      getAllRows("market_selection").catch(() => []),
    ]);

    const activeIdeas = ideas.filter((i) => i.status === "active");
    const pendingIdeas = ideas.filter((i) => i.status === "pending_approval");
    const errors = status.filter((s) => s.status === "error");

    parts.push(`【事業案】合計${ideas.length}件、アクティブ${activeIdeas.length}件、承認待ち${pendingIdeas.length}件`);

    if (activeIdeas.length > 0) {
      const names = activeIdeas.slice(0, 5).map((i) => i.name || i.id).join(", ");
      parts.push(`アクティブ事業: ${names}`);
    }

    // Pipeline status
    if (status.length > 0) {
      const statusSummary = status.map((s) => {
        const name = s.script_name || s.script_id || "不明";
        return `${name}: ${s.status}${s.detail ? ` (${s.detail})` : ""}`;
      }).join("; ");
      parts.push(`【パイプライン】${statusSummary}`);
      if (errors.length > 0) parts.push(`エラー: ${errors.length}件`);
    }

    // Analytics
    if (analytics.length > 0) {
      const latestByBiz: Record<string, typeof analytics[0]> = {};
      for (const entry of analytics) {
        const bid = entry.business_id || "";
        if (!latestByBiz[bid] || (entry.date || "") > (latestByBiz[bid].date || "")) {
          latestByBiz[bid] = entry;
        }
      }
      const totalPV = Object.values(latestByBiz).reduce((s, e) => s + (Number(e.pageviews) || 0), 0);
      const totalCV = Object.values(latestByBiz).reduce((s, e) => s + (Number(e.conversions) || 0), 0);
      parts.push(`【LP成果】合計PV: ${totalPV}, CV: ${totalCV}`);

      if (/lp|成果|pv|コンバージョン|分析|アクセス/.test(lower)) {
        for (const [bid, data] of Object.entries(latestByBiz).slice(0, 5)) {
          const idea = ideas.find((i) => i.id === bid);
          parts.push(`  ${idea?.name || bid}: PV${data.pageviews} / CV${data.conversions} / 直帰率${data.bounce_rate}%`);
        }
      }
    }

    // SNS
    if (snsPosts.length > 0) {
      const recent = snsPosts.slice(-5).reverse();
      parts.push(`【SNS】直近投稿${snsPosts.length}件`);
      if (/sns|投稿|ツイート/.test(lower)) {
        for (const p of recent) {
          parts.push(`  [${p.platform}] ${p.status} — ${(p.content || "").substring(0, 40)}`);
        }
      }
    }

    // Market selection data
    if (/市場|選定|スコア|承認|セグメント|パイプライン|abc0|自律/.test(lower) && marketSelection.length > 0) {
      const selected = marketSelection.filter((m) => m.status === "selected");
      const recent = marketSelection.slice(-10);
      parts.push(`【市場選定】合計${marketSelection.length}件、承認済み${selected.length}件`);
      for (const m of recent) {
        parts.push(`  ${m.status === "selected" ? "✅" : "⏳"} ${m.market_name || ""}: スコア${m.total_score || "N/A"} (${m.recommended_entry_angle || ""})`);
      }
    }

    // Learning memory
    if (/戦略|提案|改善|学習|メモリ/.test(lower)) {
      const memories = await getAllRows("learning_memory").catch(() => []);
      const active = memories.filter((m) => m.status === "active").slice(-5);
      if (active.length > 0) {
        parts.push(`【学習メモリ】直近${active.length}件:`);
        for (const m of active) {
          parts.push(`  [${m.category}] ${(m.content || "").substring(0, 60)}`);
        }
      }
    }

    // Sheet URLs — always include so AI can link to relevant sheets
    const sheetUrls = await getSheetUrls([
      "business_ideas", "market_research", "market_selection",
      "competitor_analysis", "analytics", "settings",
      "pipeline_status", "sns_posts", "knowledge_base",
    ]).catch(() => ({}));

    if (Object.keys(sheetUrls).length > 0) {
      parts.push(`【シートリンク】`);
      for (const [name, url] of Object.entries(sheetUrls)) {
        parts.push(`  ${name}: ${url}`);
      }
    }
  } catch (err) {
    console.error("[bot-query] Error gathering data:", err);
  }

  return parts.join("\n");
}

/** Generate a natural AI response using Gemini */
async function generateAIResponse(
  userMessage: string,
  dataContext: string,
): Promise<string | null> {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) return null;

  try {
    const genAI = new GoogleGenerativeAI(apiKey);
    const model = genAI.getGenerativeModel({
      model: process.env.GEMINI_CHAT_MODEL || "gemini-2.5-pro",
      systemInstruction: `あなたはBVA System（事業検証自動化システム）の戦略パートナーAIです。
ユーザー（CEO）とGoogle Chatで壁打ち・議論・戦略検討を行います。

# あなたの役割
- ClaudeやChatGPTのように**思考力のある自然な対話**をする
- ユーザーの質問や相談に対して、深い洞察と戦略的な視点で回答する
- 単なるデータ読み上げではなく、**分析・考察・提案**を含めて回答する
- 壁打ち相手として、ユーザーの考えを深掘りしたり、別の視点を提示する
- システムの設計意図や仕組みの質問には、正確かつ分かりやすく説明する

# BVA System の仕組み（あなたが熟知しているシステム）

## パイプライン全体フロー
A_市場調査 → B_市場選定 → (ユーザー承認) → C_競合調査 → 0_事業案生成 → 1_LP生成 → 2_SNS投稿 → 3_フォーム営業 → 4_分析改善 → 5_Slackレポート → 7_学習エンジン

### 🤖 自律型パイプライン（orchestrate_abc0）
A→P(痛み抽出)→B→自動承認→C→0→U(ユニットエコノミクス)→E(チェックリスト164項目評価)→I(インタビュースクリプト生成)→自己反省
を**完全無人で一気通貫実行**するモード。実行には「自律パイプライン実行して」「abc0回して」「パイプライン全部やって」等。
自己反省で生成されたimprovement_suggestions/risks/next_actionsはpipeline_improvement_logに蓄積され、次回実行に自動反映される。

## 各ステップの設計

### A. 市場調査
exploration_marketsで指定した市場ごとに、Claude API(温度0.5)でPEST分析・TAM/SAM算出・業界構造・キープレイヤー・顧客ペインポイント・参入障壁を抽出。市場あたりexploration_segments_per_market件のサブセグメントに分解。

### B. 市場選定（5軸スコアリング）
市場調査結果を5軸で定量評価（各1-10点、加重合計）:
1. distortion_depth（市場の歪み・非効率）× 重み3
2. entry_barrier（参入障壁の低さ）× 重み2
3. bpo_feasibility（SaaS/BPO化可能性）× 重み2
4. growth（成長率・将来性）× 重み1.5
5. capability_fit（AI×事業開発との適合度）× 重み1.5
上位selection_top_n件を承認候補として提示。

### C. 競合調査
承認済み市場ごとに直接/間接/代替の3タイプの競合を分析。ギャップ機会（未充足ニーズ、DX化機会、価格帯空白、サービス品質差）を特定。

### 0. 事業案生成
全コンテキスト（ナレッジベース、市場調査、競合分析、学習履歴、CEOプロフィール、方向性メモ）を統合し、Claude API(温度0.8)で事業アイデアを生成。

### 1-7. 後続パイプライン
LP自動生成 → SNS自動投稿 → フォーム営業 → GA4/GSCデータ分析 → Slack日次レポート → 学習エンジン（実績フィードバック）

## 設定項目
target_industries(ターゲット業界), trend_keywords(トレンドKW), exploration_markets(探索市場), ideas_per_run(生成数), exploration_scoring_weights(スコアリング重み), selection_top_n(承認候補数), competitors_per_market(競合分析数), idea/market_direction_notes(方向性メモ), use_ceo_profile(CEO適合スコアリング)

# 設定の自動更新機能
ユーザーが方針変更や設定変更を指示した場合、回答末尾に以下の形式で設定更新タグを出力してください：

[SETTINGS_UPDATE]
{"key":"value"}
[/SETTINGS_UPDATE]

変更可能キー:
- target_industries: ターゲット業界（カンマ区切り）
- trend_keywords: トレンドキーワード（カンマ区切り）
- exploration_markets: 探索対象市場（カンマ区切り）
- ideas_per_run: 1回の生成数
- idea_direction_notes: 事業案の方向性メモ（上書き）
- market_direction_notes: 市場探索の方向性メモ（上書き）
- orchestrator_auto_approve: 自律パイプラインの自動承認ON/OFF（true/false）
- orchestrator_min_score_threshold: 自動承認の最低スコア閾値

★ 重要: 「追加」vs「変更」の判断ルール:
  - 「〜も追加して」「〜も入れて」→ 既存値にカンマで追加
  - 「〜に変更して」「〜にして」「〜で」「〜を追加して」（「も」がない）→ 既存値を置き換え
  - 「〜〇〇領域で〜を追加して」のように新しいテーマを示す場合 → 探索市場を新テーマに置き換え
  - 迷ったらユーザーに「既存の設定に追加ですか？置き換えですか？」と確認する
★ 方向性の指示（「〜を重視して」「〜は除外」等）→ direction_notes に保存
★ 具体的な業界・市場の指示 → target_industries / exploration_markets に保存
★ 複合的な指示は複数キーを同時に更新してよい
★ 質問や分析依頼にはタグ不要。明確な方針変更・指示の場合のみ付ける。

# 絶対厳守ルール（ハルシネーション禁止）
- **存在しないファイル名、関数名、ID、URL、数値を絶対に捏造してはならない**
- 実績データに含まれていない数値やログを「証跡」として出力してはならない
- 知らないことは「確認できていません」「データがありません」と正直に答える
- ユーザーがコードの変更やパイプラインの改修を求めた場合は「設定変更は対応可能ですが、コードの改修はClaude Code（開発環境）での対応が必要です」と伝える

# あなたにできること / できないこと
できること:
- 設定値の参照・更新（SETTINGS_UPDATEで変更可能なキーのみ）
- 実績データの参照・分析（スプレッドシートに存在するデータのみ）
- システム設計の説明（上記の仕組みセクションの知識）
- 戦略的な壁打ち・議論・提案
- パイプラインの実行指示（「市場調査を実行して」等）

できないこと:
- Pythonスクリプトやコードの直接改修
- スケジューラのON/OFF切り替え
- スプレッドシートの行の削除・ステータスの直接書き換え（設定シート以外）
- 外部URLの取得やスクレイピング
- できないことを「やりました」と嘘の報告すること

# スプレッドシートリンク
各シートのデータを参照・説明する際は、該当シートへの直接リンクを回答に含めてください。
リンクは実績データ内の【シートリンク】セクションから取得できます。Slack/Google Chat形式: <URL|表示テキスト>
例: 「市場調査結果は <https://docs.google.com/.../edit#gid=123|📊market_research> で確認できます」

パイプライン実行後の通知には各ステップの関連シートへのリンクが自動付与されます。

# 回答スタイル
- **自然な日本語で対話**する。箇条書きの羅列だけでなく、考察や意見を交えて回答
- ユーザーの意図を汲み取り、表面的な回答ではなく本質的な回答をする
- 「〜だと思います」「〜が重要なポイントですね」等、壁打ちパートナーらしい語り口
- Google Chat形式のマークダウン（*太字*）を適宜使う
- 必要に応じて長めの回答もOK（設計や戦略の議論は十分な深さで）
- データがある場合は根拠として引用しつつ、データがなくてもシステム知識や一般的な事業開発の知見で回答する
- 「この観点も検討してみてはいかがでしょう」等、ユーザーの思考を広げる提案も積極的に
- できないことを求められたら、正直に伝えた上で代替案を提示する`,
    });

    // Fetch current settings to inject into prompt
    const currentSettings = await getCurrentSettings();

    const prompt = `ユーザーの質問に、戦略パートナーとして自然な対話で回答してください。

【質問の意図を判断する基準】
- 「フロー」「条件」「仕組み」「設計」「どうやって」→ システム設計（system instructionの知識）に基づいて回答
- 「状況」「成果」「何件」「結果」→ 以下の実績データに基づいて回答
- 設定変更・方針変更の指示 → 設定を更新し、回答末尾にSETTINGS_UPDATEタグを付ける
- 戦略相談・壁打ち → システム知識 + 実績データ + あなた自身の知見を組み合わせて回答

${currentSettings ? `【現在の設定値】\n${currentSettings}\n` : ""}
【現在の実績データ（参考）】
${dataContext || "まだ実績データはありません。"}

【ユーザーのメッセージ】
${userMessage}`;

    const result = await model.generateContent({
      contents: [{ role: "user", parts: [{ text: prompt }] }],
      generationConfig: {
        maxOutputTokens: 4096,
        temperature: 0.7,
      },
    });
    const rawText = result.response.text();
    if (!rawText || !rawText.trim()) return null;

    // Apply settings updates if the AI included SETTINGS_UPDATE tags
    const settingsApplied = await applySettingsUpdate(rawText);

    // Strip the tags from the response sent to the user
    let reply = stripSettingsTag(rawText);

    // Append confirmation if settings were updated
    if (settingsApplied.length > 0) {
      const keyLabels: Record<string, string> = {
        target_industries: "ターゲット業界",
        trend_keywords: "トレンドKW",
        exploration_markets: "探索市場",
        ideas_per_run: "生成数/回",
        idea_direction_notes: "事業案方向性メモ",
        market_direction_notes: "市場探索方向性メモ",
      };
      const updated = settingsApplied.map((k) => keyLabels[k] || k).join(", ");
      reply += `\n\n⚙️ _設定を更新しました: ${updated}_`;
    }

    return reply;
  } catch (err) {
    console.error("[bot-query] AI generation failed, falling back to template:", err);
  }

  return null;
}

function getSystemExplanation(): string {
  return (
    `🤖 *BVA System（事業検証自動化ボット）とは？*\n\n` +
    `かんたんに言うと「新しいビジネスのアイデアを考えて、テストして、結果を教えてくれるロボット」です！\n\n` +
    `*🔄 やっていること:*\n` +
    `1️⃣ *アイデアを考える* — AIが市場を調べて「こんなビジネスどう？」と提案\n` +
    `2️⃣ *ホームページを作る* — 提案されたビジネスのWebページ（LP）を自動生成\n` +
    `3️⃣ *SNSで宣伝する* — X（Twitter）に自動で投稿して人を集める\n` +
    `4️⃣ *結果を分析する* — 何人見た？反応は？を自動レポート\n` +
    `5️⃣ *改善し続ける* — データを元に、もっと良くする方法を学習\n\n` +
    `*💬 話しかけ方:*\n` +
    `• 「パイプライン状況教えて」→ 各システムの動作状況\n` +
    `• 「LP成果どう？」→ ページのアクセス数やコンバージョン\n` +
    `• 「今後の戦略を提案して」→ データに基づく改善提案\n` +
    `• 「SNS投稿の頻度を上げて」→ 指示として保存、次回から反映\n\n` +
    `📊 ダッシュボード: https://lp-app-pi.vercel.app/dashboard`
  );
}

async function getLPPerformanceSummary(): Promise<string> {
  try {
    const [analytics, ideas] = await Promise.all([
      getAllRows("analytics").catch(() => []),
      getAllRows("business_ideas").catch(() => []),
    ]);

    const activeIdeas = ideas.filter((i) => i.status === "active");

    if (analytics.length === 0) {
      return "📊 *LP成果レポート*\n\nまだ分析データがありません。分析・改善パイプラインの実行後にデータが蓄積されます。";
    }

    const latestByBiz: Record<string, typeof analytics[0]> = {};
    for (const entry of analytics) {
      const bid = entry.business_id || "";
      if (!latestByBiz[bid] || (entry.date || "") > (latestByBiz[bid].date || "")) {
        latestByBiz[bid] = entry;
      }
    }

    const totalPV = Object.values(latestByBiz).reduce((s, e) => s + (Number(e.pageviews) || 0), 0);
    const totalSessions = Object.values(latestByBiz).reduce((s, e) => s + (Number(e.sessions) || 0), 0);
    const totalCV = Object.values(latestByBiz).reduce((s, e) => s + (Number(e.conversions) || 0), 0);

    let text = `📊 *LP成果レポート*（直近データ）\n\n`;
    text += `• 合計PV: *${totalPV}*\n`;
    text += `• 合計セッション: *${totalSessions}*\n`;
    text += `• 合計コンバージョン: *${totalCV}*\n`;
    text += `• アクティブ事業数: *${activeIdeas.length}*\n\n`;

    const entries = Object.entries(latestByBiz);
    if (entries.length > 0) {
      text += `*事業別内訳:*\n`;
      for (const [bid, data] of entries.slice(0, 5)) {
        const idea = ideas.find((i) => i.id === bid);
        const name = idea?.name || bid;
        const pv = Number(data.pageviews) || 0;
        const cv = Number(data.conversions) || 0;
        const br = Number(data.bounce_rate) || 0;
        text += `  • ${name}: PV ${pv} / CV ${cv} / 直帰率 ${br.toFixed(1)}%\n`;
      }
    }

    return text;
  } catch (err) {
    console.error("LP performance query error:", err);
    return "⚠️ LP成果データの取得中にエラーが発生しました。";
  }
}

async function getPipelineStatus(): Promise<string> {
  try {
    const status = await getAllRows("pipeline_status").catch(() => []);

    if (status.length === 0) {
      return "⚙️ *パイプライン状況*\n\nまだステータスデータがありません。";
    }

    const labels: Record<string, string> = {
      A_market_research: "🔍 市場調査",
      B_market_selection: "🎯 市場選定",
      C_competitor_analysis: "⚔️ 競合調査",
      "0_idea_generator": "💡 事業案生成",
      "1_lp_generator": "🚀 LP生成",
      "2_sns_poster": "📢 SNS投稿",
      "3_form_sales": "✉️ フォーム営業",
      "4_analytics_reporter": "📈 分析・改善",
      "5_slack_reporter": "💬 Slackレポート",
      "6_ads_monitor": "💰 広告監視",
      "7_learning_engine": "🧠 学習エンジン",
      "8_ads_creator": "📣 広告自動出稿",
      orchestrate_abc0: "🤖 自律型パイプライン",
    };

    const statusEmoji: Record<string, string> = {
      success: "✅", error: "❌", running: "🔄", idle: "⏸️",
    };

    let text = `⚙️ *パイプライン状況*\n\n`;
    for (const row of status) {
      const scriptKey = row.script_name || row.script_id || "";
      const label = labels[scriptKey] || scriptKey;
      const emoji = statusEmoji[row.status] || "❓";
      const detail = row.detail || "";
      const lastRun = (row.timestamp || row.last_run || "").substring(0, 16) || "—";
      text += `${emoji} ${label}: ${detail} (${lastRun})\n`;
    }

    return text;
  } catch (err) {
    console.error("Pipeline status query error:", err);
    return "⚠️ パイプライン状況の取得中にエラーが発生しました。";
  }
}

async function getSNSSummary(): Promise<string> {
  try {
    const posts = await getAllRows("sns_posts").catch(() => []);
    const recent = posts.slice(-10).reverse();

    if (recent.length === 0) {
      return "📢 *SNS投稿状況*\n\nまだ投稿データがありません。";
    }

    let text = `📢 *SNS投稿状況*（直近${recent.length}件）\n\n`;
    for (const post of recent) {
      const platform = post.platform || "—";
      const status = post.status || "—";
      const date = (post.posted_at || post.created_at || "").substring(0, 10);
      const content = (post.content || "").substring(0, 40);
      text += `• [${platform}] ${status} — ${content}… (${date})\n`;
    }

    return text;
  } catch (err) {
    console.error("SNS summary query error:", err);
    return "⚠️ SNS投稿データの取得中にエラーが発生しました。";
  }
}

async function getIdeasSummary(): Promise<string> {
  try {
    const ideas = await getAllRows("business_ideas").catch(() => []);
    const active = ideas.filter((i) => i.status === "active");
    const pending = ideas.filter((i) => i.status === "pending_approval");

    let text = `💡 *事業案サマリー*\n\n`;
    text += `• 総数: *${ideas.length}*件\n`;
    text += `• アクティブ: *${active.length}*件\n`;
    text += `• 承認待ち: *${pending.length}*件\n\n`;

    if (active.length > 0) {
      text += `*アクティブ事業:*\n`;
      for (const idea of active.slice(0, 5)) {
        const score = idea.score ? `(スコア: ${idea.score})` : "";
        text += `  • ${idea.name || idea.id} ${score}\n`;
      }
    }

    return text;
  } catch (err) {
    console.error("Ideas summary query error:", err);
    return "⚠️ 事業案データの取得中にエラーが発生しました。";
  }
}

async function getOverview(): Promise<string> {
  try {
    const [ideas, status, analytics] = await Promise.all([
      getAllRows("business_ideas").catch(() => []),
      getAllRows("pipeline_status").catch(() => []),
      getAllRows("analytics").catch(() => []),
    ]);

    const activeIdeas = ideas.filter((i) => i.status === "active").length;
    const errors = status.filter((s) => s.status === "error").length;
    const totalPV = analytics.reduce((s, e) => s + (Number(e.pageviews) || 0), 0);

    let text = `📋 *MarketProbe 概要レポート*\n\n`;
    text += `• アクティブ事業: *${activeIdeas}*件\n`;
    text += `• パイプラインエラー: *${errors}*件\n`;
    text += `• 累計PV: *${totalPV}*\n\n`;
    text += `詳しくは「LP成果教えて」「パイプライン状況」などと聞いてください。`;

    return text;
  } catch (err) {
    console.error("Overview query error:", err);
    return "⚠️ データの取得中にエラーが発生しました。ダッシュボードをご確認ください。";
  }
}

async function getStrategySummary(): Promise<string> {
  try {
    const [ideas, status, analytics, snsPosts] = await Promise.all([
      getAllRows("business_ideas").catch(() => []),
      getAllRows("pipeline_status").catch(() => []),
      getAllRows("analytics").catch(() => []),
      getAllRows("sns_posts").catch(() => []),
    ]);

    const activeIdeas = ideas.filter((i) => i.status === "active");
    const pendingIdeas = ideas.filter((i) => i.status === "pending_approval");
    const errors = status.filter((s) => s.status === "error");

    const latestByBiz: Record<string, typeof analytics[0]> = {};
    for (const entry of analytics) {
      const bid = entry.business_id || "";
      if (!latestByBiz[bid] || (entry.date || "") > (latestByBiz[bid].date || "")) {
        latestByBiz[bid] = entry;
      }
    }
    const totalPV = Object.values(latestByBiz).reduce((s, e) => s + (Number(e.pageviews) || 0), 0);
    const totalCV = Object.values(latestByBiz).reduce((s, e) => s + (Number(e.conversions) || 0), 0);
    const avgBounce = Object.values(latestByBiz).length > 0
      ? Object.values(latestByBiz).reduce((s, e) => s + (Number(e.bounce_rate) || 0), 0) / Object.values(latestByBiz).length
      : 0;

    const recentSNS = snsPosts.filter((p) => {
      const d = p.posted_at || p.created_at || "";
      const weekAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
      return d >= weekAgo;
    });

    let text = `🎯 *MarketProbe 戦略サマリー*\n\n`;

    text += `*📊 現状:*\n`;
    text += `• アクティブ事業: *${activeIdeas.length}*件`;
    if (pendingIdeas.length > 0) text += ` / 承認待ち: *${pendingIdeas.length}*件`;
    text += `\n`;
    text += `• 累計PV: *${totalPV}* / CV: *${totalCV}*`;
    if (avgBounce > 0) text += ` / 平均直帰率: *${avgBounce.toFixed(1)}%*`;
    text += `\n`;
    text += `• 直近7日のSNS投稿: *${recentSNS.length}*件\n`;
    if (errors.length > 0) {
      text += `• ⚠️ パイプラインエラー: *${errors.length}*件\n`;
    }

    text += `\n*💡 データに基づく提案:*\n`;

    if (totalPV === 0 && totalCV === 0) {
      text += `• LP未稼働: まずLP生成パイプラインを実行し、アクセスデータを蓄積しましょう\n`;
    } else if (totalCV === 0 && totalPV > 0) {
      text += `• PVはあるがCV未発生: CTAの改善やフォーム最適化を検討してください\n`;
    } else if (avgBounce > 70) {
      text += `• 直帰率が高い（${avgBounce.toFixed(0)}%）: ヘッドラインの訴求力やページ読み込み速度を見直しましょう\n`;
    }

    if (recentSNS.length < 3) {
      text += `• SNS投稿頻度が低い: 投稿頻度を上げてリーチ拡大を図りましょう\n`;
    }

    if (pendingIdeas.length > 0) {
      text += `• 承認待ちの事業案が *${pendingIdeas.length}*件: ダッシュボードで確認・承認してください\n`;
    }

    if (errors.length > 0) {
      const errorScripts = errors.map((e) => e.script_id || "不明").join(", ");
      text += `• エラー発生中: ${errorScripts} — ダッシュボードで詳細を確認してください\n`;
    }

    if (activeIdeas.length > 0 && totalPV > 0 && totalCV > 0 && avgBounce < 50 && errors.length === 0) {
      text += `• ✅ 全体的に順調です。スケール戦略（新規事業案追加、広告出稿拡大）を検討しましょう\n`;
    }

    text += `\n詳細は「LP成果教えて」「パイプライン状況」「SNS投稿状況」で確認できます。`;

    return text;
  } catch (err) {
    console.error("Strategy summary error:", err);
    return "⚠️ 戦略サマリーの生成中にエラーが発生しました。ダッシュボードをご確認ください。";
  }
}

// ---------------------------------------------------------------------------
// Directive save handler
// ---------------------------------------------------------------------------

const categoryLabels: Record<string, string> = {
  lp_optimization: "LP改善",
  sns_strategy: "SNS戦略",
  form_sales: "フォーム営業",
  idea_generation: "事業案生成",
  general: "一般",
};

export async function saveDirective(
  message: string,
  source: string,
  userId: string,
  channel: string,
): Promise<string> {
  const category = classifyCategory(message);
  const now = new Date().toISOString().replace("T", " ").substring(0, 16);
  const id = generateId();

  try {
    await ensureSheetExists("learning_memory", LEARNING_HEADERS);
    await appendRows("learning_memory", [[
      id, "directive", source, category,
      message, JSON.stringify({ user: userId, channel }),
      "1.0", "high", "active", "0", now, "",
    ]]);

    return (
      `✅ 了解しました。学習メモリに保存しました。\n` +
      `> カテゴリ: *${categoryLabels[category] || category}*\n` +
      `> 内容: ${message.substring(0, 100)}${message.length > 100 ? "..." : ""}\n` +
      `次回のパイプライン実行から反映されます。`
    );
  } catch (err) {
    console.error("Failed to save directive:", err);
    return "⚠️ 保存中にエラーが発生しました。ダッシュボードから再度お試しください。";
  }
}
