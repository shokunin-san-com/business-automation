import { NextRequest, NextResponse } from "next/server";
import { getAllRows, appendRows } from "@/lib/sheets";

/**
 * POST /api/lp/guard
 *
 * LP creation guard — checks if all V2 pipeline conditions are met
 * before allowing LP generation.
 *
 * Body: { run_id: string }
 *
 * Conditions checked:
 * 1. gate_decision_log has PASS record for this run_id
 *    OR exploration_lane_log has ACTIVE record
 * 2. competitor_20_log has records for this run_id (10+ companies)
 * 3. offer_3_log has 3 records with all 7 required fields non-empty
 *
 * Returns:
 * - { status: "READY" } when all conditions met
 * - { status: "BLOCKED", missing: [...] } when conditions not met
 *
 * Also records result in lp_ready_log sheet.
 */

const OFFER_REQUIRED_FIELDS = [
  "payer",
  "offer_name",
  "deliverable",
  "time_to_value",
  "price",
  "replaces",
  "upsell",
];

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const runId = body.run_id;

    if (!runId) {
      return NextResponse.json(
        { error: "run_id is required" },
        { status: 400 },
      );
    }

    const missing: string[] = [];

    // 1. Gate check
    let gateOk = false;
    try {
      const gateRows = await getAllRows("gate_decision_log");
      const gatePass = gateRows.filter(
        (r) => r.run_id === runId && r.status === "PASS",
      );
      if (gatePass.length > 0) {
        gateOk = true;
      } else {
        // Fallback: check exploration lane
        const laneRows = await getAllRows("exploration_lane_log");
        const laneActive = laneRows.filter(
          (r) => r.run_id === runId && r.status === "ACTIVE",
        );
        if (laneActive.length > 0) {
          gateOk = true;
        }
      }
    } catch {
      // Sheet may not exist yet
    }
    if (!gateOk) {
      missing.push("gate_decision_log: PASSレコードなし");
    }

    // 2. Competitor check
    let competitorOk = false;
    try {
      const compRows = await getAllRows("competitor_20_log");
      const compForRun = compRows.filter((r) => r.run_id === runId);
      if (compForRun.length >= 10) {
        competitorOk = true;
      } else {
        missing.push(
          `competitor_20_log: ${compForRun.length}社のみ（10社以上必要）`,
        );
      }
    } catch {
      missing.push("competitor_20_log: データ取得エラー");
    }

    // 3. Offer check
    let offerOk = false;
    try {
      const offerRows = await getAllRows("offer_3_log");
      const offersForRun = offerRows.filter((r) => r.run_id === runId);
      if (offersForRun.length >= 3) {
        const allFieldsComplete = offersForRun.slice(0, 3).every((o) =>
          OFFER_REQUIRED_FIELDS.every((f) => (o[f] || "").trim() !== ""),
        );
        if (allFieldsComplete) {
          offerOk = true;
        } else {
          missing.push("offer_3_log: 必須フィールドに空欄あり");
        }
      } else {
        missing.push(
          `offer_3_log: ${offersForRun.length}案のみ（3案必要）`,
        );
      }
    } catch {
      missing.push("offer_3_log: データ取得エラー");
    }

    const status = gateOk && competitorOk && offerOk ? "READY" : "BLOCKED";
    const blockedReason = missing.join(" / ");
    const now = new Date().toISOString().slice(0, 16).replace("T", " ");

    // Record in lp_ready_log
    try {
      await appendRows("lp_ready_log", [
        [
          runId,
          now,
          String(gateOk),
          String(competitorOk),
          String(offerOk),
          status,
          blockedReason,
        ],
      ]);
    } catch (err) {
      console.warn("[lp/guard] Failed to write lp_ready_log:", err);
    }

    return NextResponse.json({
      status,
      run_id: runId,
      gate_ok: gateOk,
      competitor_ok: competitorOk,
      offer_ok: offerOk,
      missing: missing.length > 0 ? missing : undefined,
    });
  } catch (err) {
    console.error("[lp/guard] Error:", err);
    return NextResponse.json(
      { error: String(err) },
      { status: 500 },
    );
  }
}
