import { NextRequest, NextResponse } from "next/server";
import { getAllRows, appendRows, updateCell } from "@/lib/sheets";

/**
 * POST /api/deal — Create a new deal from an inquiry
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { inquiry_id, business_id, run_id, company_name, deal_value } = body;

    if (!inquiry_id || !business_id) {
      return NextResponse.json(
        { error: "inquiry_id and business_id are required" },
        { status: 400 },
      );
    }

    const dealId = `deal_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const now = new Date().toISOString();

    await appendRows("deal_pipeline", [
      [
        dealId,
        inquiry_id,
        business_id,
        run_id || "",
        "inquiry",       // initial stage
        company_name || "",
        deal_value || "0",
        now,             // created_at
        now,             // updated_at
        "",              // closed_at
        "",              // won_lost
        "",              // close_reason
      ],
    ]);

    // Update inquiry status to contacted
    await updateCell("inquiry_log", "inquiry_id", inquiry_id, "status", "contacted");

    return NextResponse.json({ ok: true, deal_id: dealId });
  } catch (err) {
    console.error("Deal POST error:", err);
    return NextResponse.json(
      { ok: false, error: "Failed to create deal" },
      { status: 500 },
    );
  }
}

/**
 * PUT /api/deal — Update deal stage
 */
export async function PUT(request: NextRequest) {
  try {
    const body = await request.json();
    const { deal_id, stage, won_lost, close_reason, deal_value } = body;

    if (!deal_id || !stage) {
      return NextResponse.json(
        { error: "deal_id and stage are required" },
        { status: 400 },
      );
    }

    const validStages = ["inquiry", "qualification", "proposal", "negotiation", "won", "lost"];
    if (!validStages.includes(stage)) {
      return NextResponse.json(
        { error: `Invalid stage. Must be one of: ${validStages.join(", ")}` },
        { status: 400 },
      );
    }

    const now = new Date().toISOString();
    await updateCell("deal_pipeline", "deal_id", deal_id, "stage", stage);
    await updateCell("deal_pipeline", "deal_id", deal_id, "updated_at", now);

    if (stage === "won" || stage === "lost") {
      await updateCell("deal_pipeline", "deal_id", deal_id, "closed_at", now);
      await updateCell("deal_pipeline", "deal_id", deal_id, "won_lost", won_lost || stage);
      if (close_reason) {
        await updateCell("deal_pipeline", "deal_id", deal_id, "close_reason", close_reason);
      }
    }

    if (deal_value !== undefined) {
      await updateCell("deal_pipeline", "deal_id", deal_id, "deal_value", String(deal_value));
    }

    return NextResponse.json({ ok: true, deal_id, stage });
  } catch (err) {
    console.error("Deal PUT error:", err);
    return NextResponse.json(
      { ok: false, error: "Failed to update deal" },
      { status: 500 },
    );
  }
}

/**
 * GET /api/deal — List deals with optional filters
 * ?business_id=xxx&stage=proposal
 */
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const businessId = searchParams.get("business_id");
    const stage = searchParams.get("stage");

    let rows = await getAllRows("deal_pipeline");

    if (businessId) {
      rows = rows.filter((r) => r.business_id === businessId);
    }
    if (stage) {
      rows = rows.filter((r) => r.stage === stage);
    }

    return NextResponse.json({ deals: rows, total: rows.length });
  } catch (err) {
    console.error("Deal GET error:", err);
    return NextResponse.json({ deals: [], total: 0, error: String(err) });
  }
}
