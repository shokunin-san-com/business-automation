import { NextRequest, NextResponse } from "next/server";
import { updateCell } from "@/lib/sheets";

/**
 * POST /api/market-selection/approve
 *
 * Approve or reject a market selection.
 * Body: { market_id: string, action: "approve" | "reject" }
 */
export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { market_id, action } = body;

    if (!market_id || !["approve", "reject"].includes(action)) {
      return NextResponse.json(
        { error: "market_id and action (approve|reject) are required" },
        { status: 400 },
      );
    }

    const newStatus = action === "approve" ? "selected" : "rejected";

    const updated = await updateCell(
      "market_selection",
      "id",
      market_id,
      "status",
      newStatus,
    );

    if (!updated) {
      return NextResponse.json(
        { error: `Market selection not found: ${market_id}` },
        { status: 404 },
      );
    }

    // Also update reviewed_by
    await updateCell(
      "market_selection",
      "id",
      market_id,
      "reviewed_by",
      "dashboard",
    );

    return NextResponse.json({ ok: true, market_id, status: newStatus });
  } catch (err) {
    console.error("Market approval error:", err);
    return NextResponse.json(
      { error: "Failed to update market selection" },
      { status: 500 },
    );
  }
}
