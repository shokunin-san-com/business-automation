import { NextResponse } from "next/server";
import { getAllRows } from "@/lib/sheets";

/**
 * GET /api/ideas
 *
 * V2: Returns active markets from gate_decision_log + offer_3_log + lp_ready_log.
 * Replaces V1 business_ideas sheet.
 */

interface MarketIdea {
  id: string;       // run_id
  name: string;     // micro_market or offer_name
  category: string; // payer
  description: string; // deliverable or blackout_hypothesis
  target_audience: string; // payer
  status: string;   // derived from lp_ready_log
  created_at: string;
  has_lp: boolean;
}

export async function GET() {
  try {
    const [gateRows, offerRows, lpReady, lpContent, rejectRows] = await Promise.all([
      getAllRows("gate_decision_log").catch(() => []),
      getAllRows("offer_3_log").catch(() => []),
      getAllRows("lp_ready_log").catch(() => []),
      getAllRows("lp_content").catch(() => []),
      getAllRows("ceo_reject_log").catch(() => []),
    ]);

    // Build LP content lookup
    const lpRunIds = new Set(
      lpContent.map((r) => r.business_id || r.run_id || "").filter(Boolean),
    );

    // Build lp_ready status lookup
    const readyStatus: Record<string, string> = {};
    for (const r of lpReady) {
      if (r.run_id) readyStatus[r.run_id] = r.status || "";
    }

    // Build rejection/approval lookup
    const decidedRunIds = new Set(
      rejectRows
        .filter((r) => r.type === "run_approve" || r.type === "run_reject")
        .map((r) => r.run_id),
    );

    // Collect unique run_ids from PASS gates
    const passGates = gateRows.filter((r) => r.status === "PASS");
    const seenRuns = new Map<string, typeof passGates[0]>();
    for (const g of passGates) {
      if (g.run_id && !seenRuns.has(g.run_id)) {
        seenRuns.set(g.run_id, g);
      }
    }

    // Build offer lookup
    const offersByRun: Record<string, typeof offerRows[0]> = {};
    for (const o of offerRows) {
      if (o.run_id && !offersByRun[o.run_id]) {
        offersByRun[o.run_id] = o;
      }
    }

    const mapped: MarketIdea[] = [];
    for (const [runId, gate] of seenRuns) {
      const offer = offersByRun[runId];
      const lpStatus = readyStatus[runId] || "";
      const isDecided = decidedRunIds.has(runId);

      let status = "draft";
      if (lpStatus === "READY" && !isDecided) status = "pending_approval";
      else if (lpStatus === "READY" && isDecided) status = "active";
      else if (lpStatus === "BLOCKED") status = "blocked";

      mapped.push({
        id: runId,
        name: gate.micro_market || offer?.offer_name || runId.slice(0, 8),
        category: offer?.payer || gate.payer || "",
        description: offer?.deliverable || gate.blackout_hypothesis || "",
        target_audience: offer?.payer || gate.payer || "",
        status,
        created_at: gate.timestamp || "",
        has_lp: lpRunIds.has(runId),
      });
    }

    const active = mapped.filter((i) => i.status === "active");
    const draft = mapped.filter((i) => i.status === "pending_approval" || i.status === "draft");
    const archived = mapped.filter((i) => i.status === "blocked");

    return NextResponse.json({
      active,
      draft,
      archived,
      totalCount: mapped.length,
      activeCount: active.length,
    });
  } catch {
    return NextResponse.json({
      active: [],
      draft: [],
      archived: [],
      totalCount: 0,
      activeCount: 0,
    });
  }
}
