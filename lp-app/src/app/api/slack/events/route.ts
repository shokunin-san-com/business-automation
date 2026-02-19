import { NextRequest, NextResponse } from "next/server";
import crypto from "crypto";
import { appendRows, ensureSheetExists } from "@/lib/sheets";

/**
 * POST /api/slack/events
 *
 * Receives Slack Events API payloads.
 * Handles:
 *   - url_verification (initial setup challenge)
 *   - app_mention events (@MarketProbe messages)
 *
 * Setup:
 *   1. In Slack App settings → "Event Subscriptions" → enable
 *   2. Set Request URL to: https://<your-domain>/api/slack/events
 *   3. Subscribe to "app_mention" bot event
 *   4. Set SLACK_SIGNING_SECRET and SLACK_BOT_TOKEN in .env.local
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

/** Classify the message into a directive category using keyword matching. */
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

/** Post a reply message to a Slack channel using Bot Token. */
async function postSlackReply(
  channel: string,
  threadTs: string,
  text: string,
): Promise<void> {
  const token = process.env.SLACK_BOT_TOKEN;
  if (!token) return;

  await fetch("https://slack.com/api/chat.postMessage", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      channel,
      thread_ts: threadTs,
      text,
    }),
  });
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

  const payload = JSON.parse(rawBody);

  // 2. URL verification challenge (initial setup)
  if (payload.type === "url_verification") {
    return NextResponse.json({ challenge: payload.challenge });
  }

  // 3. Event callback
  if (payload.type === "event_callback") {
    const event = payload.event;

    // Handle app_mention
    if (event?.type === "app_mention") {
      // Strip the bot mention from the message text
      // Format: "<@U12345> some message"
      const rawText: string = event.text || "";
      const message = rawText.replace(/<@[A-Z0-9]+>/g, "").trim();

      if (!message) {
        await postSlackReply(
          event.channel,
          event.ts,
          "メッセージ内容が空です。要望を書いてメンションしてください。",
        );
        return new Response("", { status: 200 });
      }

      // Save as directive to learning_memory
      const category = classifyCategory(message);
      const now = new Date().toISOString().replace("T", " ").substring(0, 16);
      const id = generateId();
      const slackUser = event.user || "slack_user";

      try {
        await ensureSheetExists("learning_memory", LEARNING_HEADERS);
        await appendRows("learning_memory", [[
          id, "directive", "slack_mention", category,
          message, JSON.stringify({ slack_user: slackUser, channel: event.channel }),
          "1.0", "high", "active", "0", now, "",
        ]]);

        const categoryLabels: Record<string, string> = {
          lp_optimization: "LP改善",
          sns_strategy: "SNS戦略",
          form_sales: "フォーム営業",
          idea_generation: "事業案生成",
          general: "一般",
        };

        await postSlackReply(
          event.channel,
          event.ts,
          `✅ 了解しました。学習メモリに保存しました。\n` +
          `> カテゴリ: *${categoryLabels[category] || category}*\n` +
          `> 内容: ${message.substring(0, 100)}${message.length > 100 ? "..." : ""}\n` +
          `次回のパイプライン実行から反映されます。`,
        );
      } catch (err) {
        console.error("Failed to save Slack mention directive:", err);
        await postSlackReply(
          event.channel,
          event.ts,
          "⚠️ 保存中にエラーが発生しました。ダッシュボードから再度お試しください。",
        );
      }

      return new Response("", { status: 200 });
    }
  }

  // Default: acknowledge
  return new Response("", { status: 200 });
}
