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
// Agent task detection — routes to autonomous agent via /api/agent/execute
// ---------------------------------------------------------------------------

/** Patterns that indicate the message should be routed to the autonomous agent */
const AGENT_TASK_PATTERNS: { pattern: RegExp; taskType: string }[] = [
  // Schedule registration
  { pattern: /スケジュール.*(登録|追加|作成|設定)/, taskType: "schedule_register" },
  { pattern: /(登録|追加|作成|設定).*スケジュール/, taskType: "schedule_register" },
  { pattern: /スケジューラ.*(登録|追加|新規)/, taskType: "schedule_register" },
  { pattern: /(cron|定期).*(登録|設定|追加)/i, taskType: "schedule_register" },
  { pattern: /毎(朝|日|週|晩|夜).*(登録|設定|追加)/, taskType: "schedule_register" },
  // Code fix
  { pattern: /コード.*(修正|直して|変更|更新|fix)/i, taskType: "code_fix" },
  { pattern: /(修正|直して|fix|bug|バグ).*(\.py|\.ts|コード|スクリプト)/i, taskType: "code_fix" },
  { pattern: /(\.py|\.ts|\.js).*(修正|直して|変更|更新)/, taskType: "code_fix" },
  // Code read
  { pattern: /コード.*(確認|見て|読んで|見せて|チェック)/, taskType: "code_read" },
  { pattern: /(ファイル|ソース).*(確認|見て|読んで|チェック)/, taskType: "code_read" },
  // Health check via agent
  { pattern: /エージェント.*(巡回|チェック|確認|診断)/, taskType: "health_check" },
  { pattern: /(深い|詳細|徹底).*(チェック|確認|調査)/, taskType: "health_check" },
  // Explicit agent invocation
  { pattern: /エージェント(で|に|を使って|経由)/, taskType: "general" },
  { pattern: /^agent\s+/i, taskType: "general" },
];

/**
 * Detect if the message should be routed to the autonomous agent.
 * Returns null for normal queries / execution commands.
 */
export function isAgentTask(
  text: string,
): { taskType: string } | null {
  // Never treat queries as agent tasks
  if (isQuery(text)) return null;
  const lower = text.toLowerCase();
  for (const { pattern, taskType } of AGENT_TASK_PATTERNS) {
    if (pattern.test(lower)) return { taskType };
  }
  return null;
}

/**
 * Submit a task to the autonomous agent.
 * Directly calls the Cloud Run Jobs API (same pattern as handleExecutionCommand)
 * instead of going through /api/agent/execute to avoid Vercel internal fetch issues.
 */
export async function handleAgentTask(
  message: string,
  triggeredBy: string,
  source: string,
): Promise<string> {
  try {
    const jobId = "agent-orchestrator";
    const token = await getAccessToken();
    const url = `https://${GCP_REGION}-run.googleapis.com/v2/projects/${GCP_PROJECT}/locations/${GCP_REGION}/jobs/${jobId}:run`;

    // Build container override with AGENT_TASK and AGENT_CONTEXT env vars
    const envOverrides: { name: string; value: string }[] = [
      { name: "AGENT_TASK", value: message },
      {
        name: "AGENT_CONTEXT",
        value: JSON.stringify({ triggered_by: triggeredBy, source }),
      },
    ];

    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        overrides: {
          containerOverrides: [
            {
              env: envOverrides,
            },
          ],
        },
      }),
    });

    if (!res.ok) {
      const errText = await res.text();
      console.error(`[bot-query] Agent execute error for ${jobId}:`, errText);
      return `⚠️ エージェントタスクの実行に失敗しました（${res.status}）。`;
    }

    const result = await res.json();
    const executionName = result.metadata?.name || result.name || "";

    // Log execution (best-effort)
    try {
      await ensureSheetExists("execution_logs", [
        "timestamp", "job_name", "trigger", "status", "detail", "executed_by",
      ]);
      await appendRows("execution_logs", [[
        new Date().toISOString(),
        "agent-orchestrator",
        "chat-bridge",
        "triggered",
        `Task: ${message.substring(0, 100)} | Execution: ${executionName}`,
        triggeredBy,
      ]]);
    } catch { /* best-effort */ }

    return (
      `🤖 *エージェントタスク受付済み*\n` +
      `> タスク: ${message.substring(0, 100)}\n` +
      `> 実行ID: \`${executionName || "starting..."}\`\n\n` +
      `自律エージェントが処理を開始しました。完了次第、結果を通知します。`
    );
  } catch (err) {
    console.error("[bot-query] Error submitting agent task:", err);
    return "⚠️ エージェントタスクの送信中にエラーが発生しました。";
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
  // Note: "どういう" alone is too broad — it matches "どういうサービスなら〜" (strategic question).
  // Only match when explicitly asking about the system/bot itself.
  if (/なんの(チャット|アプリ|ボット|システム)|何これ|使い方|ヘルプ|help|わかるように|説明して|どういう(システム|ボット|仕組み|アプリ|ツール)/.test(lower)) {
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
    // Always include basic overview — fetch both V2 and legacy data
    const [ideas, status, analytics, snsPosts, marketSelection, microMarkets, gateLog, competitor20, offer3, lpReady, explorationLane] = await Promise.all([
      getAllRows("business_ideas").catch(() => []),
      getAllRows("pipeline_status").catch(() => []),
      getAllRows("analytics").catch(() => []),
      getAllRows("sns_posts").catch(() => []),
      getAllRows("market_selection").catch(() => []),
      getAllRows("micro_market_list").catch(() => []),
      getAllRows("gate_decision_log").catch(() => []),
      getAllRows("competitor_20_log").catch(() => []),
      getAllRows("offer_3_log").catch(() => []),
      getAllRows("lp_ready_log").catch(() => []),
      getAllRows("exploration_lane_log").catch(() => []),
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

    // V2 data — always include for context-rich AI responses
    if (microMarkets.length > 0) {
      const a1qPass = microMarkets.filter((m) => m.a1q_status === "PASS");
      parts.push(`【V2 マイクロ市場】合計${microMarkets.length}件、A1q PASS: ${a1qPass.length}件`);
      if (/市場|マイクロ|ゲート|探索|参入/.test(lower)) {
        const recent = microMarkets.slice(-10);
        for (const m of recent) {
          parts.push(`  ${m.a1q_status === "PASS" ? "✅" : "❌"} ${m.micro_market || ""} (${m.industry || ""})`);
        }
      }
    }

    if (gateLog.length > 0) {
      const passed = gateLog.filter((g) => g.status === "PASS");
      const failed = gateLog.filter((g) => g.status === "FAIL");
      parts.push(`【V2 深層ゲート】PASS: ${passed.length}件、FAIL: ${failed.length}件`);
      for (const g of gateLog.slice(-5)) {
        const missing = g.missing_items ? ` (未達: ${g.missing_items})` : "";
        parts.push(`  ${g.status === "PASS" ? "✅" : "❌"} ${g.micro_market || ""}${missing}`);
      }
    }

    if (explorationLane.length > 0) {
      const active = explorationLane.filter((e) => e.status === "ACTIVE");
      parts.push(`【V2 探索レーン】ACTIVE: ${active.length}件`);
      for (const e of explorationLane.slice(-3)) {
        parts.push(`  [${e.status}] ${e.market || ""} (期限: ${e.deadline || "N/A"}, 面談: ${e.interview_count || 0}件)`);
      }
    }

    if (competitor20.length > 0) {
      const uniqueMarkets = new Set(competitor20.map((c) => c.market));
      parts.push(`【V2 競合20社分析】${competitor20.length}社 (${uniqueMarkets.size}市場分)`);
      if (/競合|穴|ギャップ|オファー|サービス/.test(lower)) {
        for (const c of competitor20.slice(-5)) {
          parts.push(`  ${c.company_name || ""}: ${c.url || "URL未取得"}`);
        }
      }
    }

    if (offer3.length > 0) {
      parts.push(`【V2 即決オファー】${offer3.length}件`);
      for (const o of offer3.slice(-6)) {
        parts.push(`  #${o.offer_num || ""} ${o.offer_name || ""}: ${o.price || ""} → ${o.payer || ""}`);
      }
    }

    if (lpReady.length > 0) {
      const ready = lpReady.filter((l) => l.status === "READY");
      const blocked = lpReady.filter((l) => l.status === "BLOCKED");
      parts.push(`【V2 LP作成ガード】READY: ${ready.length}件、BLOCKED: ${blocked.length}件`);
    }

    // Legacy market selection data (V1 — reference only)
    if (/市場|選定|スコア|承認|セグメント|パイプライン|abc0|自律/.test(lower) && marketSelection.length > 0) {
      const selected = marketSelection.filter((m) => m.status === "selected");
      const recent = marketSelection.slice(-10);
      parts.push(`【旧V1 市場選定（参考）】合計${marketSelection.length}件、承認済み${selected.length}件`);
      for (const m of recent) {
        parts.push(`  ${m.status === "selected" ? "✅" : "⏳"} ${m.market_name || ""}: 旧スコア${m.total_score || "N/A"}`);
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
      "settings", "micro_market_list", "gate_decision_log",
      "exploration_lane_log", "competitor_20_log", "offer_3_log",
      "lp_ready_log", "pipeline_status", "execution_logs",
      "business_ideas", "market_research", "analytics", "sns_posts",
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

# BVA System の仕組み（実装済み・本番稼働中）

## ★★ 最重要: V2パイプライン（本番）★★
MarketProbe V2は「証拠ベースのPASS/FAILゲート方式」に完全移行済みです。
**旧V1のスコアリング（点数・重み・ランキング）は完全廃止されています。**

### V2パイプラインフロー（orchestrate_v2）:
\`\`\`
A0(マイクロ市場生成) → A1q(簡易ゲート) → A1d(深層8条件ゲート) → EX(探索レーン)
→ C(競合20社分析) → 0(即決オファー3案) → LP作成ガード → 通知
\`\`\`

### 各ステップ:
- **A0**: settingsのexploration_marketsから30-50のマイクロ市場を生成。マイクロ市場 = 業界×業務×職種×タイミング×規制+意図語。→ micro_market_listシート
- **A1q(簡易ゲート)**: 支払い証拠URL≧1 + カテゴリ証拠(需要/本気度/追い風)≧1でPASS/FAIL → micro_market_listのa1q_status
- **A1d(深層ゲート)**: 上位5市場に8条件チェック。**全条件クリアでPASS、1つでも欠けたらFAIL**:
  (a)支払い者特定(部署+役職) (b)価格証拠URL3+ (c)追い風URL2+ (d)本気度URL2+ (e)検索指標(検索vol/CPC/トレンド) (f)競合URL10社 (g)穴3つ+証拠URL (h)黒字化仮説(単価×10顧客)
  → gate_decision_logシート
- **EX(探索レーン)**: A1dでFAILだが支払い者特定済み+3条件以上 → 7日限定のインタビュー調査 → exploration_lane_logシート
- **C(競合20社)**: PASS市場の競合20社を7種URL(本体/価格/事例/採用/広告/展示会/最新情報)で分析。穴トップ3抽出 → competitor_20_logシート
- **0(即決オファー3案)**: 穴を埋める即決オファー。7必須フィールド: payer, offer_name, deliverable, time_to_value, price, replaces, upsell → offer_3_logシート
- **LP作成ガード**: ゲートPASS + 競合10社以上 + オファー3案完備 → lp_ready_logシート

### V2絶対ルール:
1. **スコアリング禁止** — 点数・重み・ランキングは一切使わない
2. **偽URL禁止** — URLを捏造したら即FAIL
3. **推定禁止** — 「たぶんPASS」は不可。実証拠URLが必要
4. **PASS/FAILのみ** — 条件付きPASSは存在しない

## 自律エージェント機能（実装済み）
チャットからコード修正・ビルド・デプロイ・スケジュール管理が可能:
- 「スケジュール登録して」→ Cloud Schedulerに自動登録
- 「コードを確認して/修正して」→ GitHubからコード読み取り・修正・PR作成
- 「ビルドして」→ Cloud Buildトリガー
- 「深いチェックして」→ ログ・シートの包括的な診断

## 設定項目
target_industries, trend_keywords, exploration_markets, ideas_per_run,
idea_direction_notes(事業案方向性), market_direction_notes(市場探索方向性), competitors_per_market

# 設定の自動更新機能
ユーザーが方針変更や設定変更を指示した場合、回答末尾に以下の形式で設定更新タグを出力:

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
  - 「〜も追加して」→ 既存値にカンマで追加
  - 「〜に変更して」「〜にして」→ 既存値を置き換え
  - 迷ったらユーザーに確認する
★ 方向性の指示 → direction_notes に保存
★ 具体的な業界・市場の指示 → target_industries / exploration_markets に保存
★ 質問や分析依頼にはタグ不要。明確な方針変更・指示の場合のみ付ける。

# 絶対厳守ルール（ハルシネーション禁止）
- **存在しないファイル名、関数名、ID、URL、数値を絶対に捏造してはならない**
- 実績データに含まれていない数値やログを「証跡」として出力してはならない
- 知らないことは「確認できていません」「データがありません」と正直に答える
- コードの改修やスケジュール管理が必要な場合は「エージェント経由で対応可能です。例: 『コード修正して』『スケジュール登録して』と話しかけてください」と伝える

# あなたにできること / できないこと
できること:
- 設定値の参照・更新（SETTINGS_UPDATEで変更可能なキーのみ）
- 実績データの参照・分析（スプレッドシートに存在するデータのみ）
- システム設計の説明
- 戦略的な壁打ち・議論・提案
- パイプラインの実行指示（「市場調査を実行して」「V2パイプライン実行して」等）

できないこと（エージェント経由で可能なものは案内する）:
- スプレッドシートの行の削除・ステータスの直接書き換え（設定シート以外）
- 外部URLの取得やスクレイピング
- できないことを「やりました」と嘘の報告すること

# スプレッドシートリンク
各シートのデータを参照・説明する際は、実績データ内の【シートリンク】セクションから取得できます。
Slack/Google Chat形式: <URL|表示テキスト>

# 回答スタイル
- **自然な日本語で対話**する。箇条書きの羅列だけでなく、考察や意見を交えて回答
- ユーザーの意図を汲み取り、表面的な回答ではなく本質的な回答をする
- 壁打ちパートナーらしい語り口で深い議論を展開する
- Google Chat形式のマークダウン（*太字*）を適宜使う
- データがある場合は根拠として引用。なくても事業開発の知見で回答する
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
