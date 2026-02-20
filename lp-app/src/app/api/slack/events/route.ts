import { NextRequest, NextResponse } from "next/server";
import crypto from "crypto";
import { isQuery, handleDataQuery, saveDirective } from "@/lib/bot-query";

/**
 * POST /api/slack/events
 *
 * Receives Slack Events API payloads.
 * Handles:
 *   - url_verification (initial setup challenge)
 *   - app_mention events (@MarketProbe messages)
 *   - message events (DM to bot / channel messages)
 */

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

/** Post a reply message to a Slack channel using Bot Token. */
async function postSlackReply(
  channel: string,
  threadTs: string | null,
  text: string,
): Promise<void> {
  const token = process.env.SLACK_BOT_TOKEN;
  if (!token) return;

  const body: Record<string, string> = { channel, text };
  if (threadTs) body.thread_ts = threadTs;

  await fetch("https://slack.com/api/chat.postMessage", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
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

    // Ignore bot's own messages to prevent loops
    if (event?.bot_id || event?.subtype === "bot_message") {
      return new Response("", { status: 200 });
    }

    // Handle app_mention
    if (event?.type === "app_mention") {
      const rawText: string = event.text || "";
      const message = rawText.replace(/<@[A-Z0-9]+>/g, "").trim();

      if (!message) {
        await postSlackReply(
          event.channel,
          event.ts,
          "メッセージ内容が空です。質問や要望を書いてメンションしてください。\n例: `@MarketProbe 直近のLP成果を教えて`",
        );
        return new Response("", { status: 200 });
      }

      if (isQuery(message)) {
        const reply = await handleDataQuery(message);
        await postSlackReply(event.channel, event.ts, reply);
      } else {
        const reply = await saveDirective(message, "slack_mention", event.user || "slack_user", event.channel);
        await postSlackReply(event.channel, event.ts, reply);
      }

      return new Response("", { status: 200 });
    }

    // Handle DM messages (message.im)
    if (event?.type === "message" && event?.channel_type === "im") {
      const message = (event.text || "").trim();

      if (!message) {
        return new Response("", { status: 200 });
      }

      if (isQuery(message)) {
        const reply = await handleDataQuery(message);
        await postSlackReply(event.channel, null, reply);
      } else {
        const reply = await saveDirective(message, "slack_dm", event.user || "slack_user", event.channel);
        await postSlackReply(event.channel, null, reply);
      }

      return new Response("", { status: 200 });
    }
  }

  // Default: acknowledge
  return new Response("", { status: 200 });
}
