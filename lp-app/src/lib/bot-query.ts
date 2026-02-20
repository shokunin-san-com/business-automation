/**
 * Shared bot query/directive logic — used by Slack and Google Chat handlers.
 */
import crypto from "crypto";
import { getAllRows, appendRows, ensureSheetExists } from "@/lib/sheets";

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
  return false;
}

// ---------------------------------------------------------------------------
// Data query handlers
// ---------------------------------------------------------------------------

export async function handleDataQuery(message: string): Promise<string> {
  const lower = message.toLowerCase();

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
