import { NextRequest, NextResponse } from "next/server";
import { getAllRows, appendRows } from "@/lib/sheets";

/**
 * POST /api/ceo-review
 *
 * CEO rejection API for V2 pipeline.
 *
 * Body:
 * {
 *   type: "market" | "offer",
 *   run_id: string,
 *   rejected_item: string,    // market name or offer name
 *   reject_reason: string,
 *   reviewed_by?: string,     // defaults to "CEO"
 * }
 *
 * market版: gate_decision_logのPASSが複数 → 却下で1つに絞る
 * offer版: offer_3_logの3案 → 却下で残り案を絞る
 *
 * Records rejection in ceo_reject_log sheet.
 */

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { type, run_id, rejected_item, reject_reason, reviewed_by } = body;

    if (!type || !run_id || !rejected_item || !reject_reason) {
      return NextResponse.json(
        { error: "type, run_id, rejected_item, reject_reason are required" },
        { status: 400 },
      );
    }

    if (type !== "market" && type !== "offer") {
      return NextResponse.json(
        { error: "type must be 'market' or 'offer'" },
        { status: 400 },
      );
    }

    const now = new Date().toISOString().slice(0, 16).replace("T", " ");
    const reviewer = reviewed_by || "CEO";

    // Record rejection
    await appendRows("ceo_reject_log", [
      [run_id, type, rejected_item, reject_reason, reviewer, now],
    ]);

    // Return remaining items after rejection
    let remaining: string[] = [];

    if (type === "market") {
      const gateRows = await getAllRows("gate_decision_log");
      const passForRun = gateRows.filter(
        (r) => r.run_id === run_id && r.status === "PASS",
      );
      // Check all rejections for this run
      const rejectRows = await getAllRows("ceo_reject_log");
      const rejectedMarkets = new Set(
        rejectRows
          .filter((r) => r.run_id === run_id && r.type === "market")
          .map((r) => r.rejected_item),
      );
      remaining = passForRun
        .map((r) => r.micro_market)
        .filter((m) => !rejectedMarkets.has(m));
    } else {
      const offerRows = await getAllRows("offer_3_log");
      const offersForRun = offerRows.filter((r) => r.run_id === run_id);
      const rejectRows = await getAllRows("ceo_reject_log");
      const rejectedOffers = new Set(
        rejectRows
          .filter((r) => r.run_id === run_id && r.type === "offer")
          .map((r) => r.rejected_item),
      );
      remaining = offersForRun
        .map((r) => r.offer_name)
        .filter((n) => !rejectedOffers.has(n));
    }

    return NextResponse.json({
      ok: true,
      type,
      rejected: rejected_item,
      remaining,
      remaining_count: remaining.length,
    });
  } catch (err) {
    console.error("[ceo-review] Error:", err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}

/**
 * GET /api/ceo-review?run_id=xxx
 *
 * Get current review status for a run.
 */
export async function GET(request: NextRequest) {
  try {
    const runId = request.nextUrl.searchParams.get("run_id");
    if (!runId) {
      return NextResponse.json(
        { error: "run_id query parameter required" },
        { status: 400 },
      );
    }

    // Get PASS markets
    const gateRows = await getAllRows("gate_decision_log");
    const passMarkets = gateRows.filter(
      (r) => r.run_id === runId && r.status === "PASS",
    );

    // Get offers
    const offerRows = await getAllRows("offer_3_log");
    const offers = offerRows.filter((r) => r.run_id === runId);

    // Get rejections
    const rejectRows = await getAllRows("ceo_reject_log");
    const rejections = rejectRows.filter((r) => r.run_id === runId);

    const rejectedMarkets = new Set(
      rejections.filter((r) => r.type === "market").map((r) => r.rejected_item),
    );
    const rejectedOffers = new Set(
      rejections.filter((r) => r.type === "offer").map((r) => r.rejected_item),
    );

    return NextResponse.json({
      run_id: runId,
      markets: {
        total: passMarkets.length,
        items: passMarkets.map((m) => ({
          micro_market: m.micro_market,
          rejected: rejectedMarkets.has(m.micro_market),
          payer: m.payer,
        })),
        needs_review: passMarkets.length > 1 && passMarkets.length - rejectedMarkets.size > 1,
      },
      offers: {
        total: offers.length,
        items: offers.map((o) => ({
          offer_name: o.offer_name,
          payer: o.payer,
          price: o.price,
          rejected: rejectedOffers.has(o.offer_name),
        })),
        needs_review: offers.length > 1 && offers.length - rejectedOffers.size > 1,
      },
      rejections: rejections.map((r) => ({
        type: r.type,
        item: r.rejected_item,
        reason: r.reject_reason,
        by: r.reviewed_by,
        at: r.timestamp,
      })),
    });
  } catch (err) {
    console.error("[ceo-review] GET Error:", err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
