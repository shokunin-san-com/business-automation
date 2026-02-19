import { NextRequest, NextResponse } from "next/server";
import { updateCell, getAllRows } from "@/lib/sheets";

/**
 * POST /api/slack/approve
 * Body: { idea_id: string, action: "approve" | "reject", user?: string }
 *
 * Called from:
 *   1. Dashboard UI buttons
 *   2. Slack Interactive Message callback (forwarded from /api/slack/interactive)
 *
 * Updates the business_ideas sheet directly via Google Sheets API.
 * No more Python child_process.exec!
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

    const newStatus = action === "approve" ? "active" : "archived";
    const actionLabel = action === "approve" ? "\u627F\u8A8D" : "\u5374\u4E0B";
    const actor = user || "dashboard";

    // Update business_ideas sheet: set status column
    try {
      await updateCell("business_ideas", "id", idea_id, "status", newStatus);
    } catch (err) {
      console.error("Failed to update Sheets:", err);
      // Continue anyway — best effort
    }

    // Look up idea name for the Slack notification
    let ideaName = idea_id;
    try {
      const ideas = await getAllRows("business_ideas");
      const idea = ideas.find((i) => i.id === idea_id);
      if (idea?.name) ideaName = idea.name;
    } catch { /* ignore */ }

    // Send Slack notification about the decision
    try {
      const webhookUrl = process.env.SLACK_WEBHOOK_URL;
      if (webhookUrl) {
        const emoji = action === "approve" ? ":white_check_mark:" : ":x:";
        await fetch(webhookUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text: `${emoji} \u4E8B\u696D\u6848 *${ideaName}* \u304C *${actionLabel}* \u3055\u308C\u307E\u3057\u305F\u3002\n\u64CD\u4F5C\u8005: ${actor}`,
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
      message: `Idea ${idea_id} ${actionLabel}`,
    });
  } catch (err) {
    console.error("Approve error:", err);
    return NextResponse.json({ error: "Internal error" }, { status: 500 });
  }
}
