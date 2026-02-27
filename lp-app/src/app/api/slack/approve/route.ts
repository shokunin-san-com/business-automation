import { NextRequest, NextResponse } from "next/server";
import { getAllRows, appendRows } from "@/lib/sheets";

/**
 * POST /api/slack/approve
 * Body: { idea_id: string (run_id), action: "approve" | "reject", user?: string }
 *
 * V2: Records decision in ceo_reject_log sheet.
 *   - approve → type "run_approve"
 *   - reject  → type "run_reject"
 *
 * Called from:
 *   1. Dashboard UI buttons
 *   2. Slack Interactive Message callback
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { idea_id, action, user } = body as {
      idea_id: string;
      action: "approve" | "reject";
      user?: string;
    };

    if (!idea_id || !action) {
      return NextResponse.json({ error: "idea_id and action required" }, { status: 400 });
    }

    const actionLabel = action === "approve" ? "承認" : "却下";
    const actor = user || "dashboard";
    const now = new Date().toISOString().slice(0, 16).replace("T", " ");

    // V2: Record to ceo_reject_log (used for both approve and reject)
    const logType = action === "approve" ? "run_approve" : "run_reject";
    try {
      await appendRows("ceo_reject_log", [
        [idea_id, logType, "", actionLabel, actor, now],
      ]);
    } catch (err) {
      console.error("Failed to write ceo_reject_log:", err);
    }

    // Look up offer name for Slack notification
    let ideaName = idea_id.slice(0, 8);
    try {
      const offers = await getAllRows("offer_3_log");
      const offer = offers.find((o) => o.run_id === idea_id);
      if (offer?.offer_name) ideaName = offer.offer_name;
    } catch { /* ignore */ }

    // Send Slack notification
    try {
      const webhookUrl = process.env.SLACK_WEBHOOK_URL;
      if (webhookUrl) {
        const emoji = action === "approve" ? ":white_check_mark:" : ":x:";
        await fetch(webhookUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text: `${emoji} 事業案 *${ideaName}* (run: \`${idea_id.slice(0, 8)}\`) が *${actionLabel}* されました。\n操作者: ${actor}`,
          }),
        });
      }
    } catch {
      /* Slack notification is best-effort */
    }

    return NextResponse.json({
      ok: true,
      idea_id,
      action,
      message: `Run ${idea_id.slice(0, 8)} ${actionLabel}`,
    });
  } catch (err) {
    console.error("Approve error:", err);
    return NextResponse.json({ error: "Internal error" }, { status: 500 });
  }
}
