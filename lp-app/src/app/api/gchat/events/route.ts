import { NextRequest, NextResponse } from "next/server";
import { isQuery, handleDataQuery, saveDirective } from "@/lib/bot-query";

/**
 * POST /api/gchat/events
 *
 * Receives Google Chat App event payloads.
 * Handles:
 *   - ADDED_TO_SPACE (bot added to space / DM opened)
 *   - MESSAGE (user sends a message to the bot)
 *   - REMOVED_FROM_SPACE (bot removed)
 *
 * Setup:
 *   1. In GCP Console → "Chat API" → enable
 *   2. Create a Chat App with HTTP endpoint
 *   3. Set endpoint URL to: https://lp-app-pi.vercel.app/api/gchat/events
 *   4. Set GCHAT_VERIFICATION_TOKEN in .env.local (optional)
 */

// ---------------------------------------------------------------------------
// Verification (optional — Google Chat uses bearer tokens or project number)
// ---------------------------------------------------------------------------

function verifyRequest(request: NextRequest): boolean {
  const token = process.env.GCHAT_VERIFICATION_TOKEN;
  if (!token) return true; // Skip verification if not configured

  const authHeader = request.headers.get("Authorization") || "";
  if (authHeader === `Bearer ${token}`) return true;

  return false;
}

// ---------------------------------------------------------------------------
// POST handler
// ---------------------------------------------------------------------------

export async function POST(request: NextRequest) {
  // Optionally verify the request
  if (!verifyRequest(request)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 403 });
  }

  let payload;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const eventType = payload.type;

  // ---------------------------------------------------------------------------
  // ADDED_TO_SPACE — Bot was added to a space or DM
  // ---------------------------------------------------------------------------
  if (eventType === "ADDED_TO_SPACE") {
    const spaceName = payload.space?.displayName || "DM";
    return NextResponse.json({
      text: `🤖 *MarketProbe Bot* が ${spaceName} に追加されました！\n\n` +
        `質問や指示を送ってください。例:\n` +
        `• 「パイプライン状況教えて」\n` +
        `• 「LP成果どう？」\n` +
        `• 「今後の戦略を提案して」\n` +
        `• 「SNS投稿のハッシュタグを3つに増やして」（指示として保存）`,
    });
  }

  // ---------------------------------------------------------------------------
  // REMOVED_FROM_SPACE — Bot was removed
  // ---------------------------------------------------------------------------
  if (eventType === "REMOVED_FROM_SPACE") {
    // Nothing to respond to
    return new Response("", { status: 200 });
  }

  // ---------------------------------------------------------------------------
  // MESSAGE — User sent a message
  // ---------------------------------------------------------------------------
  if (eventType === "MESSAGE") {
    const messageText = payload.message?.argumentText?.trim()
      || payload.message?.text?.trim()
      || "";

    if (!messageText) {
      return NextResponse.json({
        text: "メッセージ内容が空です。質問や要望を送ってください。\n例: 「直近のLP成果を教えて」",
      });
    }

    const userId = payload.user?.displayName || payload.user?.name || "gchat_user";
    const spaceName = payload.space?.name || "unknown";

    if (isQuery(messageText)) {
      const reply = await handleDataQuery(messageText);
      return NextResponse.json({ text: reply });
    } else {
      const reply = await saveDirective(messageText, "gchat", userId, spaceName);
      return NextResponse.json({ text: reply });
    }
  }

  // ---------------------------------------------------------------------------
  // CARD_CLICKED — Button interaction (future use)
  // ---------------------------------------------------------------------------
  if (eventType === "CARD_CLICKED") {
    return NextResponse.json({
      text: "ボタンの操作はダッシュボードで行ってください: https://lp-app-pi.vercel.app/dashboard",
    });
  }

  // Default: acknowledge
  return new Response("", { status: 200 });
}
