import { NextRequest, NextResponse } from "next/server";
import { getChatAccessToken } from "@/lib/gcp-auth";
import { isQuery, handleDataQuery, saveDirective } from "@/lib/bot-query";

/**
 * POST /api/gchat/pubsub
 *
 * Receives Pub/Sub push messages from Workspace Events API subscriptions.
 * When a message is posted in a subscribed Google Chat space, this endpoint:
 *   1. Decodes the Pub/Sub message
 *   2. Fetches the full message from Chat API
 *   3. Processes the query/directive
 *   4. Posts a reply via Chat API
 *
 * This enables bot functionality in spaces with external users,
 * where Workspace Add-ons events are not delivered.
 */

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CHAT_API = "https://chat.googleapis.com/v1";

/** Fetch a message from Chat API by resource name */
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
      console.error(`[pubsub] Failed to fetch message ${messageName}: ${res.status} ${await res.text()}`);
      return null;
    }
    return await res.json();
  } catch (err) {
    console.error("[pubsub] Error fetching message:", err);
    return null;
  }
}

/** Post a reply message to a Chat space via Chat API */
async function postChatMessage(
  spaceName: string,
  text: string,
  threadName?: string,
  token?: string,
): Promise<boolean> {
  try {
    const accessToken = token || await getChatAccessToken();
    const url = `${CHAT_API}/${spaceName}/messages`;
    const body: Record<string, unknown> = { text };
    if (threadName) {
      body.thread = { name: threadName };
      // Reply in existing thread
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
      console.error(`[pubsub] Failed to post message to ${spaceName}: ${res.status} ${await res.text()}`);
      return false;
    }
    console.log(`[pubsub] Message posted to ${spaceName}`);
    return true;
  } catch (err) {
    console.error("[pubsub] Error posting message:", err);
    return false;
  }
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

  // Pub/Sub push format: { message: { data: "base64...", messageId, publishTime }, subscription }
  const pubsubMessage = body.message;
  if (!pubsubMessage?.data) {
    console.warn("[pubsub] No message data in payload");
    // Acknowledge to avoid redelivery
    return NextResponse.json({ ok: true });
  }

  // Decode the Pub/Sub message
  let eventData: {
    type?: string;
    eventType?: string;
    space?: { name?: string };
    message?: { name?: string };
    [key: string]: unknown;
  };
  try {
    const decoded = Buffer.from(pubsubMessage.data, "base64").toString("utf-8");
    eventData = JSON.parse(decoded);
    console.log("[pubsub] Event type:", eventData.type || eventData.eventType, "keys:", Object.keys(eventData));
  } catch (err) {
    console.error("[pubsub] Failed to decode message data:", err);
    return NextResponse.json({ ok: true });
  }

  // Only handle message events
  const eventType = eventData.type || eventData.eventType || "";
  if (
    !eventType.includes("MESSAGE") &&
    !eventType.includes("message") &&
    eventType !== "google.workspace.chat.message.v1.created"
  ) {
    console.log(`[pubsub] Ignoring event type: ${eventType}`);
    return NextResponse.json({ ok: true });
  }

  // Get Chat API token
  let token: string;
  try {
    token = await getChatAccessToken();
  } catch (err) {
    console.error("[pubsub] Failed to get Chat access token:", err);
    return NextResponse.json({ ok: true });
  }

  // The event may contain the message resource name or inline data
  const messageName = eventData.message?.name;
  let messageText = "";
  let senderName = "";
  let senderType = "";
  let spaceName = "";
  let threadName = "";

  if (messageName) {
    // Fetch full message from Chat API
    const fullMessage = await fetchChatMessage(messageName, token);
    if (!fullMessage) {
      console.warn("[pubsub] Could not fetch message, skipping");
      return NextResponse.json({ ok: true });
    }

    messageText = fullMessage.argumentText?.trim() || fullMessage.text?.trim() || "";
    senderName = fullMessage.sender?.displayName || fullMessage.sender?.name || "unknown";
    senderType = fullMessage.sender?.type || "";
    spaceName = fullMessage.space?.name || eventData.space?.name || "";
    threadName = fullMessage.thread?.name || "";
  } else {
    // Try to extract from inline event data
    console.log("[pubsub] No message name in event, trying inline data");
    return NextResponse.json({ ok: true });
  }

  // Skip messages from bots (avoid infinite loops)
  if (senderType === "BOT") {
    console.log("[pubsub] Skipping bot message from:", senderName);
    return NextResponse.json({ ok: true });
  }

  // Skip empty messages
  if (!messageText) {
    console.log("[pubsub] Empty message text, skipping");
    return NextResponse.json({ ok: true });
  }

  console.log(`[pubsub] Processing message from ${senderName} in ${spaceName}: "${messageText.substring(0, 50)}"`);

  // Process the message
  let reply: string;
  if (isQuery(messageText)) {
    reply = await handleDataQuery(messageText);
  } else {
    reply = await saveDirective(messageText, "gchat", senderName, spaceName);
  }

  // Post the reply
  if (spaceName) {
    await postChatMessage(spaceName, reply, threadName, token);
  } else {
    console.warn("[pubsub] No space name to reply to");
  }

  // Always acknowledge
  return NextResponse.json({ ok: true });
}
