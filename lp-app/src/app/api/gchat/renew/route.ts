import { NextRequest, NextResponse } from "next/server";
import { getWorkspaceEventsToken } from "@/lib/gcp-auth";

/**
 * GET /api/gchat/renew
 *
 * Periodically re-creates the Workspace Events API subscription for
 * the Google Chat space. Called by Cloud Scheduler (every 3h) + Vercel daily cron as fallback.
 *
 * The Workspace Events API subscription TTL is ~4 hours.
 * The previous approach (renewSubscription on lifecycle event) failed
 * because once the subscription fully expires, no more events are
 * delivered — so the renewal never triggers.
 *
 * This cron-based approach ensures the subscription is always active.
 */

const WORKSPACE_EVENTS_API = "https://workspaceevents.googleapis.com/v1";
const SPACE_NAME = "spaces/AAQA_WcWZmg";
const PUBSUB_TOPIC = "projects/marketprobe-automation/topics/gchat-space-events";

export async function GET(request: NextRequest) {
  // Verify cron secret (Vercel sets CRON_SECRET for cron jobs)
  const authHeader = request.headers.get("authorization");
  const cronSecret = process.env.CRON_SECRET;
  if (cronSecret && authHeader !== `Bearer ${cronSecret}`) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const token = await getWorkspaceEventsToken();

    // 1. List existing subscriptions for this space
    const filterStr =
      'event_types:"google.workspace.chat.message.v1.created" AND ' +
      `target_resource="//chat.googleapis.com/${SPACE_NAME}"`;

    const listRes = await fetch(
      `${WORKSPACE_EVENTS_API}/subscriptions?` +
        new URLSearchParams({ filter: filterStr }),
      { headers: { Authorization: `Bearer ${token}` } },
    );

    let existingSubs: { name: string; state?: string; expireTime?: string }[] = [];
    if (listRes.ok) {
      const listData = await listRes.json();
      existingSubs = listData.subscriptions || [];
    }

    // 2. Check if any active subscription exists with enough remaining TTL
    const now = Date.now();
    for (const sub of existingSubs) {
      if (sub.state === "ACTIVE" && sub.expireTime) {
        const expireMs = new Date(sub.expireTime).getTime();
        const remainingMs = expireMs - now;
        const remainingMin = Math.round(remainingMs / 60_000);

        // If more than 90 minutes remaining, no need to renew
        if (remainingMs > 90 * 60_000) {
          console.log(
            `[renew] Active subscription found with ${remainingMin}min remaining, skipping renewal`,
          );
          return NextResponse.json({
            ok: true,
            action: "skip",
            subscription: sub.name,
            remainingMinutes: remainingMin,
          });
        }

        console.log(
          `[renew] Active subscription expiring soon (${remainingMin}min), will recreate`,
        );
      }
    }

    // 3. Delete expired/expiring subscriptions
    for (const sub of existingSubs) {
      try {
        console.log(`[renew] Deleting subscription: ${sub.name}`);
        await fetch(`${WORKSPACE_EVENTS_API}/${sub.name}`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${token}` },
        });
      } catch (err) {
        console.warn(`[renew] Failed to delete ${sub.name}:`, err);
      }
    }

    // 4. Create new subscription
    console.log("[renew] Creating new subscription");
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

    if (!createRes.ok) {
      const errText = await createRes.text();
      console.error(`[renew] Failed to create subscription: ${createRes.status} ${errText}`);
      return NextResponse.json(
        { ok: false, error: errText },
        { status: 500 },
      );
    }

    const createData = await createRes.json();
    const newSub = createData.response || createData;
    const newExpire = newSub.expireTime || "unknown";

    console.log(`[renew] Subscription created, expires: ${newExpire}`);

    return NextResponse.json({
      ok: true,
      action: "renewed",
      subscription: newSub.name,
      expireTime: newExpire,
    });
  } catch (err) {
    console.error("[renew] Error:", err);
    return NextResponse.json(
      { ok: false, error: String(err) },
      { status: 500 },
    );
  }
}
