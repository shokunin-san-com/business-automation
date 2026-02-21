/**
 * Shared bot query/directive logic — used by Slack and Google Chat handlers.
 */
import crypto from "crypto";
import { getAllRows, appendRows, ensureSheetExists } from "@/lib/sheets";
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
    const [ideas, status, analytics, snsPosts] = await Promise.all([
      getAllRows("business_ideas").catch(() => []),
      getAllRows("pipeline_status").catch(() => []),
      getAllRows("analytics").catch(() => []),
      getAllRows("sns_posts").catch(() => []),
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
      model: process.env.GEMINI_MODEL || "gemini-2.5-flash",
      systemInstruction: `あなたはBVA System（事業検証自動化システム）のアシスタントです。
Google Chatでユーザーからの質問に答えます。

ルール:
- 日本語で簡潔に回答（Google Chat向けなので長すぎないこと）
- データに基づいて具体的に回答
- 不明な点は正直に「データがありません」と言う
- Google Chat形式のマークダウン（*太字*）を使う
- 絵文字を適度に使って読みやすく
- 戦略的な提案を求められたら、データを根拠にアクションを提案
- 最大500文字程度に収める`,
    });

    const prompt = `以下のシステムデータを参考に、ユーザーの質問に自然な文章で回答してください。

【システムデータ】
${dataContext || "データがまだありません。"}

【ユーザーの質問】
${userMessage}`;

    const result = await model.generateContent(prompt);
    const text = result.response.text();
    if (text && text.trim()) return text.trim();
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
