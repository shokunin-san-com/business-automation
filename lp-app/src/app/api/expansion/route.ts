import { NextRequest, NextResponse } from "next/server";
import { getAllRows, updateCell } from "@/lib/sheets";

/**
 * GET /api/expansion — List winning patterns
 * ?status=scaling
 */
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const status = searchParams.get("status");

    let rows = await getAllRows("winning_patterns");

    if (status) {
      rows = rows.filter((r) => r.status === status);
    }

    return NextResponse.json({ patterns: rows, total: rows.length });
  } catch (err) {
    console.error("Expansion GET error:", err);
    return NextResponse.json({ patterns: [], total: 0, error: String(err) });
  }
}

/**
 * POST /api/expansion — Update pattern status
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { pattern_id, status, scaling_stage } = body;

    if (!pattern_id) {
      return NextResponse.json(
        { error: "pattern_id is required" },
        { status: 400 },
      );
    }

    const validStatuses = ["detected", "validated", "scaling", "saturated", "archived"];
    if (status && !validStatuses.includes(status)) {
      return NextResponse.json(
        { error: `Invalid status. Must be one of: ${validStatuses.join(", ")}` },
        { status: 400 },
      );
    }

    if (status) {
      await updateCell("winning_patterns", "pattern_id", pattern_id, "status", status);
    }
    if (scaling_stage) {
      await updateCell("winning_patterns", "pattern_id", pattern_id, "scaling_stage", scaling_stage);
    }

    return NextResponse.json({ ok: true, pattern_id });
  } catch (err) {
    console.error("Expansion POST error:", err);
    return NextResponse.json(
      { ok: false, error: "Failed to update pattern" },
      { status: 500 },
    );
  }
}
