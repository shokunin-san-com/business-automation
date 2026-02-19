import { NextRequest, NextResponse } from "next/server";
import crypto from "crypto";
import { appendRows, ensureSheetExists } from "@/lib/sheets";

/**
 * POST /api/slack/command
 *
 * Receives Slack Slash Command payloads (e.g. /bva).
 * Saves the feedback text as a directive in learning_memory.
 *
 * Setup:
 *   1. In Slack App settings → "Slash Commands" → create new
 *   2. Command: /bva
 *   3. Request URL: https://<your-domain>/api/slack/command
 *   4. Description: AIパイプラインにフィードバック・指示を送信
 *   5. Usage Hint: [フィードバック内容を入力]
 */

const LEARNING_HEADERS = [
  "id", "type", "source", "category", "content",
  "context_json", "confidence", "priority", "status",
  "applied_count", "created_at", "expires_at",
];

// ---------------------------------------------------------------------------
// Signing verification
// ---------------------------------------------------------------------------

function verifySlackRequest(
  body: string,
  timestamp: string,
  signature: string,
  signingSecret: string,
): boolean {
  const baseString = `v0:${timestamp}:${body}`;
  const hmac = crypto.createHmac("sha256", signingSecret);
  hmac.update(baseString);
  const expected = `v0=${hmac.digest("hex")}`;
  return crypto.timingSafeEqual(
    Buffer.from(expected),
    Buffer.from(signature),
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generateId(): string {
  const hex = Array.from(crypto.getRandomValues(new Uint8Array(4)))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return `dir_${hex}`;
}

function classifyCategory(text: string): string {
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

// ---------------------------------------------------------------------------
// POST handler
// ---------------------------------------------------------------------------

export async function POST(request: NextRequest) {
  const rawBody = await request.text();

  // 1. Verify Slack signature
  const signingSecret = process.env.SLACK_SIGNING_SECRET || "";
  if (signingSecret) {
    const timestamp = request.headers.get("X-Slack-Request-Timestamp") || "";
    const signature = request.headers.get("X-Slack-Signature") || "";
    const age = Math.abs(Date.now() / 1000 - parseInt(timestamp));
    if (age > 300) {
      return NextResponse.json({ error: "Request too old" }, { status: 403 });
    }
    if (signature && !verifySlackRequest(rawBody, timestamp, signature, signingSecret)) {
      return NextResponse.json({ error: "Invalid signature" }, { status: 403 });
    }
  }

  // 2. Parse URL-encoded form data from Slack
  const params = new URLSearchParams(rawBody);
  const text = (params.get("text") || "").trim();
  const userName = params.get("user_name") || "slack_user";
  const userId = params.get("user_id") || "";
  const channelId = params.get("channel_id") || "";

  // 3. Validate
  if (!text) {
    // Slack expects a JSON response for slash commands
    return NextResponse.json({
      response_type: "ephemeral",
      text: "💡 使い方: `/bva LPのCTAをもっと目立つ色に変更して`\nフィードバック内容を入力してください。",
    });
  }

  // 4. Save to learning_memory
  const category = classifyCategory(text);
  const now = new Date().toISOString().replace("T", " ").substring(0, 16);
  const id = generateId();

  try {
    await ensureSheetExists("learning_memory", LEARNING_HEADERS);
    await appendRows("learning_memory", [[
      id, "directive", "slack_command", category,
      text,
      JSON.stringify({ slack_user: userName, user_id: userId, channel: channelId }),
      "1.0", "high", "active", "0", now, "",
    ]]);

    const categoryLabels: Record<string, string> = {
      lp_optimization: "LP改善",
      sns_strategy: "SNS戦略",
      form_sales: "フォーム営業",
      idea_generation: "事業案生成",
      general: "一般",
    };

    return NextResponse.json({
      response_type: "in_channel",
      text:
        `✅ フィードバックを学習メモリに保存しました。\n` +
        `> *カテゴリ:* ${categoryLabels[category] || category}\n` +
        `> *内容:* ${text.substring(0, 200)}${text.length > 200 ? "..." : ""}\n` +
        `> *投稿者:* ${userName}\n` +
        `次回のパイプライン実行から反映されます。`,
    });
  } catch (err) {
    console.error("Slash command save failed:", err);
    return NextResponse.json({
      response_type: "ephemeral",
      text: "⚠️ 保存中にエラーが発生しました。しばらく待ってから再度お試しください。",
    });
  }
}
