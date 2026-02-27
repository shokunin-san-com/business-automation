import { NextRequest, NextResponse } from "next/server";
import { appendRows } from "@/lib/sheets";

/**
 * POST /api/market-selection/approve
 *
 * V2: Records market approval/rejection in ceo_reject_log.
 * Body: { market_id: string (run_id), action: "approve" | "reject", market_name?: string }
 */
export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { market_id, action, market_name } = body;

    if (!market_id || !["approve", "reject"].includes(action)) {
      return NextResponse.json(
        { error: "market_id and action (approve|reject) are required" },
        { status: 400 },
      );
    }

    const now = new Date().toISOString().slice(0, 16).replace("T", " ");
    const logType = action === "approve" ? "run_approve" : "market";
    const rejectedItem = market_name || market_id.slice(0, 8);
    const reason = action === "approve" ? "承認" : "却下";

    await appendRows("ceo_reject_log", [
      [market_id, logType, rejectedItem, reason, "dashboard", now],
    ]);

    return NextResponse.json({ ok: true, market_id, status: action });
  } catch (err) {
    console.error("Market approval error:", err);
    return NextResponse.json(
      { error: "Failed to update market" },
      { status: 500 },
    );
  }
}
