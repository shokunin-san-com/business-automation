import { NextRequest, NextResponse } from "next/server";

/**
 * POST /api/slack/interactive
 *
 * Receives Slack Interactive Message payloads (button clicks).
 * Slack sends a URL-encoded body with a `payload` field containing JSON.
 *
 * Setup:
 *   1. Create a Slack App at https://api.slack.com/apps
 *   2. Enable "Interactivity & Shortcuts"
 *   3. Set Request URL to: https://<your-domain>/api/slack/interactive
 *   4. Optionally set SLACK_SIGNING_SECRET in .env.local for verification
 */
export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const payloadStr = formData.get("payload");

    if (!payloadStr || typeof payloadStr !== "string") {
      return NextResponse.json({ error: "Missing payload" }, { status: 400 });
    }

    const payload = JSON.parse(payloadStr);

    // Verify signing secret if configured
    const signingSecret = process.env.SLACK_SIGNING_SECRET;
    if (signingSecret) {
      // In production, verify the X-Slack-Signature header
      // For now, we trust the payload if signing secret is not set
      const timestamp = request.headers.get("X-Slack-Request-Timestamp");
      if (timestamp) {
        const age = Math.abs(Date.now() / 1000 - parseInt(timestamp));
        if (age > 300) {
          return NextResponse.json({ error: "Request too old" }, { status: 403 });
        }
      }
    }

    // Handle block_actions (button clicks)
    if (payload.type === "block_actions") {
      const action = payload.actions?.[0];
      if (!action) {
        return new Response("", { status: 200 });
      }

      const actionId = action.action_id; // "approve_idea" or "reject_idea"
      const ideaId = action.value; // The idea ID stored in button value
      const slackUser = payload.user?.name || payload.user?.username || "slack_user";

      if (actionId === "approve_idea" || actionId === "reject_idea") {
        const approveAction = actionId === "approve_idea" ? "approve" : "reject";

        // Forward to our approve endpoint
        const baseUrl = request.nextUrl.origin;
        const res = await fetch(`${baseUrl}/api/slack/approve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            idea_id: ideaId,
            action: approveAction,
            user: slackUser,
          }),
        });

        const result = await res.json();
        const emoji = approveAction === "approve" ? "\u2705" : "\u274C";
        const label = approveAction === "approve" ? "\u627F\u8A8D" : "\u5374\u4E0B";

        // Update the original Slack message to show the decision
        return NextResponse.json({
          replace_original: true,
          text: `${emoji} *${label}\u6E08\u307F* \u2014 ${slackUser} \u304C\u64CD\u4F5C\u3057\u307E\u3057\u305F`,
          blocks: [
            {
              type: "section",
              text: {
                type: "mrkdwn",
                text: `${emoji} *${label}\u6E08\u307F* \u2014 \u4E8B\u696D\u6848 \`${ideaId}\` \u3092 *${slackUser}* \u304C${label}\u3057\u307E\u3057\u305F\u3002`,
              },
            },
          ],
        });
      }
    }

    // Default: acknowledge
    return new Response("", { status: 200 });
  } catch (err) {
    console.error("Slack interactive error:", err);
    return new Response("", { status: 200 }); // Always return 200 to Slack
  }
}
