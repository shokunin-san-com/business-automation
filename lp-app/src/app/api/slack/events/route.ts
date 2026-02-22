import { NextRequest, NextResponse } from "next/server";
import { after } from "next/server";
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
 *
 * IMPORTANT: Slack retries after 3 seconds if no 200 is returned.
 * We use after() to ack immediately, then process in background.
 * X-Slack-Retry-Num header is also checked to reject retries.
 */

// Vercel max duration: give enough time for Gemini Pro to respond
export const maxDuration = 120;

// ---------------------------------------------------------------------------
// In-memory deduplication (mirrors gchat/pubsub approach)
// ---------------------------------------------------------------------------

const processedEvents = new Map<string, number>();
const DEDUP_TTL_MS = 60_000; // 60 seconds

function isDuplicate(eventId: string): boolean {
  const now = Date.now();
  for (const [key, ts] of processedEvents) {
    if (now - ts > DEDUP_TTL_MS) processedEvents.delete(key);
  }
  if (processedEvents.has(eventId)) {
    console.log(`[slack/events] Duplicate event ${eventId}, skipping`);
    return true;
  }
  processedEvents.set(eventId, now);
  return false;
}

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

  // 2. Reject Slack retries — Slack retries after 3s if no 200 returned.
  //    We ack immediately with after(), so retries are always duplicates.
  const retryNum = request.headers.get("X-Slack-Retry-Num");
  if (retryNum) {
    console.log(`[slack/events] Rejecting retry #${retryNum}`);
    return new Response("", { status: 200 });
  }

  const payload = JSON.parse(rawBody);

  // 3. URL verification challenge (initial setup)
  if (payload.type === "url_verification") {
    return NextResponse.json({ challenge: payload.challenge });
  }

  // 4. Event callback — ACK IMMEDIATELY, process in background
  if (payload.type === "event_callback") {
    const event = payload.event;
    const eventId = payload.event_id || event?.client_msg_id || event?.ts || "";

    // Ignore bot's own messages to prevent loops
    if (event?.bot_id || event?.subtype === "bot_message") {
      return new Response("", { status: 200 });
    }

    // Deduplication check
    if (eventId && isDuplicate(eventId)) {
      return new Response("", { status: 200 });
    }

    // Process in background via after() — ack Slack immediately
    after(async () => {
      try {
        await handleSlackEvent(event);
      } catch (err) {
        console.error("[slack/events] Background handler error:", err);
      }
    });

    return new Response("", { status: 200 });
  }

  // Default: acknowledge
  return new Response("", { status: 200 });
}

// ---------------------------------------------------------------------------
// Background event handler
// ---------------------------------------------------------------------------

async function handleSlackEvent(event: {
  type?: string;
  channel?: string;
  channel_type?: string;
  text?: string;
  ts?: string;
  user?: string;
  bot_id?: string;
}) {
  // Handle app_mention
  if (event?.type === "app_mention") {
    const rawText: string = event.text || "";
    const message = rawText.replace(/<@[A-Z0-9]+>/g, "").trim();
    const channel = event.channel || "";
    const threadTs = event.ts || null;

    if (!message) {
      await postSlackReply(
        channel,
        threadTs,
        "メッセージ内容が空です。質問や要望を書いてメンションしてください。\n例: `@MarketProbe 直近のLP成果を教えて`",
      );
      return;
    }

    console.log(`[slack/events] Processing mention: "${message.substring(0, 50)}"`);

    if (isQuery(message)) {
      const reply = await handleDataQuery(message);
      await postSlackReply(channel, threadTs, reply);
    } else {
      const reply = await saveDirective(message, "slack_mention", event.user || "slack_user", channel);
      await postSlackReply(channel, threadTs, reply);
    }
    return;
  }

  // Handle DM messages (message.im)
  if (event?.type === "message" && event?.channel_type === "im") {
    const message = (event.text || "").trim();
    const channel = event.channel || "";

    if (!message) return;

    console.log(`[slack/events] Processing DM: "${message.substring(0, 50)}"`);

    if (isQuery(message)) {
      const reply = await handleDataQuery(message);
      await postSlackReply(channel, null, reply);
    } else {
      const reply = await saveDirective(message, "slack_dm", event.user || "slack_user", channel);
      await postSlackReply(channel, null, reply);
    }
  }
}
