import { NextRequest, NextResponse } from "next/server";
import { isQuery, handleDataQuery, saveDirective } from "@/lib/bot-query";

/**
 * POST /api/gchat/events
 *
 * Receives Google Chat App event payloads.
 *
 * Supports BOTH:
 *   1. Workspace Add-ons format (new) — payload.chat.messagePayload / appCommandPayload
 *   2. Legacy Chat API format         — payload.type / payload.message
 *
 * Workspace Add-ons response wrapper:
 *   { hostAppDataAction: { chatDataAction: { createMessageAction: { message } } } }
 *
 * Setup:
 *   1. In GCP Console → "Chat API" → enable
 *   2. Create a Chat App with HTTP endpoint
 *   3. Set endpoint URL to: https://lp-app-pi.vercel.app/api/gchat/events
 */

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Wrap a message in Workspace Add-ons response envelope */
function addonResponse(text: string) {
  return NextResponse.json({
    hostAppDataAction: {
      chatDataAction: {
        createMessageAction: {
          message: { text },
        },
      },
    },
  });
}

/** Plain Chat API response (for legacy / curl testing) */
function legacyResponse(text: string) {
  return NextResponse.json({ text });
}

// ---------------------------------------------------------------------------
// POST handler
// ---------------------------------------------------------------------------

export async function POST(request: NextRequest) {
  let payload;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  console.log("[gchat] Received payload keys:", Object.keys(payload));

  // =========================================================================
  // Workspace Add-ons format — payload has "chat" key
  // =========================================================================
  if (payload.chat) {
    console.log("[gchat] Workspace Add-ons format detected");
    const chatEvent = payload.chat;

    // --- Message event ---
    if (chatEvent.messagePayload) {
      const message = chatEvent.messagePayload.message;
      const messageText =
        message?.argumentText?.trim() ||
        message?.text?.trim() ||
        "";

      if (!messageText) {
        return addonResponse(
          "メッセージ内容が空です。質問や要望を送ってください。\n例: 「直近のLP成果を教えて」",
        );
      }

      const sender = message?.sender;
      const userId = sender?.displayName || sender?.name || "gchat_user";
      const spaceName = chatEvent.messagePayload.space?.name || "unknown";

      // All messages go through AI (Gemini Pro) — handles queries, directives, settings changes
      const reply = await handleDataQuery(messageText);
      return addonResponse(reply);
    }

    // --- App command (slash command) event ---
    if (chatEvent.appCommandPayload) {
      return addonResponse(
        "コマンド機能は今後対応予定です。\n" +
          "質問や指示を直接メッセージで送ってください。",
      );
    }

    // --- ADDED_TO_SPACE (add-on added) ---
    if (chatEvent.addedToSpacePayload) {
      const spaceName =
        chatEvent.addedToSpacePayload.space?.displayName || "DM";
      return addonResponse(
        `🤖 *BVA System* が ${spaceName} に追加されました！\n\n` +
          `質問や指示を送ってください。例:\n` +
          `• 「パイプライン状況教えて」\n` +
          `• 「LP成果どう？」\n` +
          `• 「今後の戦略を提案して」\n` +
          `• 「SNS投稿のハッシュタグを3つに増やして」（指示として保存）`,
      );
    }

    // Default add-on ack
    return addonResponse("BVA System: メッセージを受信しました。");
  }

  // =========================================================================
  // Legacy Chat API format — payload.type = "MESSAGE" / "ADDED_TO_SPACE" etc.
  // =========================================================================
  const eventType = payload.type;
  console.log("[gchat] Legacy format, eventType:", eventType);

  // ADDED_TO_SPACE
  if (eventType === "ADDED_TO_SPACE") {
    const spaceName = payload.space?.displayName || "DM";
    return legacyResponse(
      `🤖 *BVA System* が ${spaceName} に追加されました！\n\n` +
        `質問や指示を送ってください。例:\n` +
        `• 「パイプライン状況教えて」\n` +
        `• 「LP成果どう？」\n` +
        `• 「今後の戦略を提案して」\n` +
        `• 「SNS投稿のハッシュタグを3つに増やして」（指示として保存）`,
    );
  }

  // REMOVED_FROM_SPACE
  if (eventType === "REMOVED_FROM_SPACE") {
    return new Response("", { status: 200 });
  }

  // MESSAGE
  if (eventType === "MESSAGE") {
    const messageText =
      payload.message?.argumentText?.trim() ||
      payload.message?.text?.trim() ||
      "";

    if (!messageText) {
      return legacyResponse(
        "メッセージ内容が空です。質問や要望を送ってください。\n例: 「直近のLP成果を教えて」",
      );
    }

    const userId =
      payload.user?.displayName || payload.user?.name || "gchat_user";
    const spaceName = payload.space?.name || "unknown";

    // All messages go through AI (Gemini Pro)
    const reply = await handleDataQuery(messageText);
    return legacyResponse(reply);
  }

  // CARD_CLICKED
  if (eventType === "CARD_CLICKED") {
    return legacyResponse(
      "ボタンの操作はダッシュボードで行ってください: https://lp-app-pi.vercel.app/dashboard",
    );
  }

  // Default: acknowledge
  return new Response("", { status: 200 });
}
