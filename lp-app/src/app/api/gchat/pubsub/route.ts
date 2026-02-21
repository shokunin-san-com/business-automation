import { NextRequest, NextResponse } from "next/server";
import { getChatAccessToken, getWorkspaceEventsToken } from "@/lib/gcp-auth";
import { isQuery, isExecutionCommand, handleDataQuery, handleExecutionCommand, saveDirective } from "@/lib/bot-query";

/**
 * POST /api/gchat/pubsub
 *
 * Receives Pub/Sub push messages for Google Chat.
 *
 * Supports TWO modes:
 *   1. **Chat App Pub/Sub mode** — Google Chat publishes interaction events
 *      directly to a Pub/Sub topic (configured in Chat API settings).
 *      Message data is the same JSON as the HTTP endpoint format:
 *      { type: "MESSAGE", space: {...}, message: {...}, user: {...} }
 *
 *   2. **Workspace Events API mode** — Events delivered via CloudEvents
 *      format with attributes (ce-type, ce-source, etc.) and a resource
 *      name in the data payload that needs to be fetched from Chat API.
 *
 * After processing, replies are sent via Chat API (service account auth).
 * This enables bot functionality in spaces with external users.
 */

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CHAT_API = "https://chat.googleapis.com/v1";

/** Post a reply message to a Chat space via Chat API */
async function postChatMessage(
  spaceName: string,
  text: string,
  threadName?: string,
  token?: string,
): Promise<boolean> {
  try {
    const accessToken = token || (await getChatAccessToken());
    let url = `${CHAT_API}/${spaceName}/messages`;
    const body: Record<string, unknown> = { text };
    if (threadName) {
      body.thread = { name: threadName };
      url += "?messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD";
    }
    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      console.error(
        `[pubsub] Failed to post message to ${spaceName}: ${res.status} ${await res.text()}`,
      );
      return false;
    }
    console.log(`[pubsub] Message posted to ${spaceName}`);
    return true;
  } catch (err) {
    console.error("[pubsub] Error posting message:", err);
    return false;
  }
}

/** Fetch a message from Chat API by resource name (for Workspace Events API mode) */
async function fetchChatMessage(
  messageName: string,
  token: string,
): Promise<{
  text?: string;
  argumentText?: string;
  sender?: { displayName?: string; name?: string; type?: string };
  space?: { name?: string; displayName?: string };
  name?: string;
  thread?: { name?: string };
} | null> {
  try {
    const res = await fetch(`${CHAT_API}/${messageName}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      console.error(
        `[pubsub] Failed to fetch message ${messageName}: ${res.status} ${await res.text()}`,
      );
      return null;
    }
    return await res.json();
  } catch (err) {
    console.error("[pubsub] Error fetching message:", err);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Chat App event interface (same as HTTP endpoint payload)
// ---------------------------------------------------------------------------

interface ChatAppEvent {
  type?: string;
  eventTime?: string;
  space?: { name?: string; displayName?: string; type?: string };
  message?: {
    name?: string;
    text?: string;
    argumentText?: string;
    sender?: { displayName?: string; name?: string; type?: string };
    thread?: { name?: string };
    space?: { name?: string; displayName?: string };
  };
  user?: { displayName?: string; name?: string; type?: string };
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// POST handler
// ---------------------------------------------------------------------------

export async function POST(request: NextRequest) {
  let body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  // Pub/Sub push format: { message: { data: "base64...", attributes: {...}, messageId, publishTime }, subscription }
  const pubsubMessage = body.message;
  if (!pubsubMessage?.data) {
    console.warn("[pubsub] No message data in payload");
    return NextResponse.json({ ok: true });
  }

  // Decode the Pub/Sub message data (base64 → JSON)
  let eventData: ChatAppEvent;
  try {
    const decoded = Buffer.from(pubsubMessage.data, "base64").toString("utf-8");
    eventData = JSON.parse(decoded);
    console.log(
      "[pubsub] Decoded event — type:",
      eventData.type,
      "keys:",
      Object.keys(eventData),
    );
  } catch (err) {
    console.error("[pubsub] Failed to decode message data:", err);
    return NextResponse.json({ ok: true });
  }

  // Detect which mode based on attributes or event structure
  const ceType = pubsubMessage.attributes?.["ce-type"] || "";
  const isWorkspaceEventsMode = !!ceType;
  const isChatAppMode = !!eventData.type && !ceType;

  console.log(
    `[pubsub] Mode: ${isWorkspaceEventsMode ? "WorkspaceEvents" : isChatAppMode ? "ChatApp" : "Unknown"}`,
  );

  // =========================================================================
  // Mode 1: Workspace Events API — CloudEvents format (preferred)
  // =========================================================================
  if (isWorkspaceEventsMode) {
    return handleWorkspaceEvent(eventData, ceType, pubsubMessage);
  }

  // =========================================================================
  // Mode 2: Chat App Pub/Sub — skip MESSAGE events to avoid duplicate replies
  // (Workspace Events API already handles message events)
  // =========================================================================
  if (isChatAppMode) {
    const eventType = eventData.type || "";
    if (eventType === "MESSAGE") {
      console.log("[pubsub/chatapp] Skipping MESSAGE (handled by WorkspaceEvents)");
      return NextResponse.json({ ok: true });
    }
    return handleChatAppEvent(eventData);
  }

  // Unknown format
  console.warn("[pubsub] Unknown message format, ignoring");
  return NextResponse.json({ ok: true });
}

// ---------------------------------------------------------------------------
// Chat App Pub/Sub handler
// ---------------------------------------------------------------------------

async function handleChatAppEvent(event: ChatAppEvent) {
  const eventType = event.type || "";

  // ADDED_TO_SPACE
  if (eventType === "ADDED_TO_SPACE") {
    const spaceName = event.space?.displayName || "DM";
    const reply =
      `🤖 *BVA System* が ${spaceName} に追加されました！\n\n` +
      `質問や指示を送ってください。例:\n` +
      `• 「パイプライン状況教えて」\n` +
      `• 「LP成果どう？」\n` +
      `• 「今後の戦略を提案して」\n` +
      `• 「SNS投稿のハッシュタグを3つに増やして」（指示として保存）`;

    if (event.space?.name) {
      const token = await getChatAccessToken();
      await postChatMessage(event.space.name, reply, undefined, token);
    }
    return NextResponse.json({ ok: true });
  }

  // REMOVED_FROM_SPACE
  if (eventType === "REMOVED_FROM_SPACE") {
    return NextResponse.json({ ok: true });
  }

  // MESSAGE
  if (eventType === "MESSAGE") {
    const message = event.message;
    const messageText =
      message?.argumentText?.trim() || message?.text?.trim() || "";

    if (!messageText) {
      if (event.space?.name) {
        const token = await getChatAccessToken();
        await postChatMessage(
          event.space.name,
          "メッセージ内容が空です。質問や要望を送ってください。\n例: 「直近のLP成果を教えて」",
          message?.thread?.name,
          token,
        );
      }
      return NextResponse.json({ ok: true });
    }

    // Skip messages from bots (avoid infinite loops)
    const senderType =
      message?.sender?.type || event.user?.type || "";
    if (senderType === "BOT") {
      console.log("[pubsub] Skipping bot message");
      return NextResponse.json({ ok: true });
    }

    const senderName =
      message?.sender?.displayName ||
      event.user?.displayName ||
      event.user?.name ||
      "gchat_user";
    const spaceName = event.space?.name || "unknown";

    console.log(
      `[pubsub/chatapp] Processing from ${senderName} in ${spaceName}: "${messageText.substring(0, 50)}"`,
    );

    // Process: execution command > query > directive
    let reply: string;
    const execCmd = isExecutionCommand(messageText);
    if (execCmd) {
      reply = await handleExecutionCommand(execCmd.scriptId, execCmd.label, senderName);
    } else if (isQuery(messageText)) {
      reply = await handleDataQuery(messageText);
    } else {
      reply = await saveDirective(messageText, "gchat", senderName, spaceName);
    }

    // Post the reply via Chat API
    const token = await getChatAccessToken();
    await postChatMessage(spaceName, reply, message?.thread?.name, token);

    return NextResponse.json({ ok: true });
  }

  // CARD_CLICKED
  if (eventType === "CARD_CLICKED") {
    if (event.space?.name) {
      const token = await getChatAccessToken();
      await postChatMessage(
        event.space.name,
        "ボタンの操作はダッシュボードで行ってください: https://lp-app-pi.vercel.app/dashboard",
        undefined,
        token,
      );
    }
    return NextResponse.json({ ok: true });
  }

  console.log(`[pubsub/chatapp] Ignoring event type: ${eventType}`);
  return NextResponse.json({ ok: true });
}

// ---------------------------------------------------------------------------
// Workspace Events API handler
// ---------------------------------------------------------------------------

async function handleWorkspaceEvent(
  eventData: ChatAppEvent,
  ceType: string,
  pubsubMessage: { data: string; attributes?: Record<string, string> },
) {
  // Only handle message creation events
  if (
    ceType !== "google.workspace.chat.message.v1.created" &&
    !ceType.includes("MESSAGE")
  ) {
    // Handle lifecycle events (subscription expiration reminders)
    if (ceType.includes("subscription")) {
      console.log(`[pubsub/workspace] Lifecycle event: ${ceType}`);
      // Auto-renew subscription before it expires
      await renewSubscription(eventData);
    } else {
      console.log(`[pubsub/workspace] Ignoring event type: ${ceType}`);
    }
    return NextResponse.json({ ok: true });
  }

  // With includeResource=true, the full message is embedded in eventData.message
  // With includeResource=false, we'd need to fetch it via Chat API (but service
  // account can't read user messages in external spaces, so we use includeResource=true)
  const msg = eventData.message;
  if (!msg?.name) {
    console.warn("[pubsub/workspace] No message in event data");
    console.warn("[pubsub/workspace] Event data:", JSON.stringify(eventData).substring(0, 500));
    return NextResponse.json({ ok: true });
  }

  const messageText =
    msg.argumentText?.trim() || msg.text?.trim() || "";
  const senderType = msg.sender?.type || "";
  const senderName =
    msg.sender?.displayName ||
    msg.sender?.name ||
    "unknown";
  const spaceName =
    msg.space?.name || eventData.space?.name || "";
  const threadName = msg.thread?.name || "";

  // Skip bot messages
  if (senderType === "BOT") {
    console.log("[pubsub/workspace] Skipping bot message");
    return NextResponse.json({ ok: true });
  }

  // Skip empty
  if (!messageText) {
    console.log("[pubsub/workspace] Empty message, skipping");
    return NextResponse.json({ ok: true });
  }

  // Only respond to messages that mention the bot (@BVA System)
  // argumentText is present when the bot is mentioned (text with mention stripped)
  // Also check for explicit mention in the raw text
  const rawText = msg.text || "";
  const hasMention = !!msg.argumentText || /bva|ボット|bot/i.test(rawText);
  if (!hasMention) {
    console.log("[pubsub/workspace] No bot mention, skipping");
    return NextResponse.json({ ok: true });
  }

  console.log(
    `[pubsub/workspace] Processing from ${senderName} in ${spaceName}: "${messageText.substring(0, 50)}"`,
  );

  // Process: execution command > query > directive
  let reply: string;
  const execCmd = isExecutionCommand(messageText);
  if (execCmd) {
    reply = await handleExecutionCommand(execCmd.scriptId, execCmd.label, senderName);
  } else if (isQuery(messageText)) {
    reply = await handleDataQuery(messageText);
  } else {
    reply = await saveDirective(messageText, "gchat", senderName, spaceName);
  }

  // Post the reply via Chat API (service account can post to external spaces)
  if (spaceName) {
    await postChatMessage(spaceName, reply, threadName);
  }

  return NextResponse.json({ ok: true });
}

// ---------------------------------------------------------------------------
// Subscription auto-renewal
// ---------------------------------------------------------------------------

const WORKSPACE_EVENTS_API = "https://workspaceevents.googleapis.com/v1";
const SPACE_NAME = "spaces/AAQA_WcWZmg";
const PUBSUB_TOPIC = "projects/marketprobe-automation/topics/gchat-space-events";

/** Renew an expiring Workspace Events API subscription */
async function renewSubscription(eventData: ChatAppEvent) {
  try {
    const token = await getWorkspaceEventsToken();

    // Extract current subscription name from event data if available
    const subName =
      (eventData as Record<string, unknown>).subscription as string | undefined;

    if (subName) {
      // Try to PATCH (update) the existing subscription to extend TTL
      console.log(`[pubsub/workspace] Renewing subscription: ${subName}`);
      const patchRes = await fetch(`${WORKSPACE_EVENTS_API}/${subName}`, {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          eventTypes: ["google.workspace.chat.message.v1.created"],
        }),
      });

      if (patchRes.ok) {
        console.log("[pubsub/workspace] Subscription renewed via PATCH");
        return;
      }
      console.warn(
        `[pubsub/workspace] PATCH failed (${patchRes.status}), will recreate`,
      );
    }

    // Fallback: delete + create
    if (subName) {
      console.log(`[pubsub/workspace] Deleting old subscription: ${subName}`);
      await fetch(`${WORKSPACE_EVENTS_API}/${subName}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
    }

    // Create new subscription
    console.log("[pubsub/workspace] Creating new subscription");
    const createRes = await fetch(`${WORKSPACE_EVENTS_API}/subscriptions`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        targetResource: `//chat.googleapis.com/${SPACE_NAME}`,
        eventTypes: ["google.workspace.chat.message.v1.created"],
        notificationEndpoint: { pubsubTopic: PUBSUB_TOPIC },
        payloadOptions: { includeResource: true },
      }),
    });

    if (createRes.ok) {
      const data = await createRes.json();
      console.log("[pubsub/workspace] New subscription created:", JSON.stringify(data).substring(0, 200));
    } else {
      const err = await createRes.text();
      console.error(`[pubsub/workspace] Failed to create subscription: ${createRes.status} ${err.substring(0, 300)}`);
    }
  } catch (err) {
    console.error("[pubsub/workspace] Error renewing subscription:", err);
  }
}
