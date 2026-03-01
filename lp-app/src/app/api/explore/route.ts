import { NextResponse } from "next/server";
import { getAllRows } from "@/lib/sheets";

/**
 * GET /api/explore
 *
 * Returns pipeline run history with per-step progress and filter stats.
 *
 * Data sources (all filtered by run_id):
 *   - settings_snapshot       -> run_id list + timestamp
 *   - business_model_types    -> Layer 1 counts
 *   - business_combos         -> Layer 2 counts
 *   - demand_verification_log -> Phase C results
 *   - gate_decision_log       -> Phase D results
 *   - offer_3_log             -> Phase E results
 *   - lp_ready_log            -> Phase F results
 *   - ceo_reject_log          -> approval status
 */
export async function GET() {
  try {
    const [snapshots, typeRows, comboRows, demandRows, gateRows, offerRows, lpReady, ceoLog] =
      await Promise.all([
        getAllRows("settings_snapshot").catch(() => []),
        getAllRows("business_model_types").catch(() => []),
        getAllRows("business_combos").catch(() => []),
        getAllRows("demand_verification_log").catch(() => []),
        getAllRows("gate_decision_log").catch(() => []),
        getAllRows("offer_3_log").catch(() => []),
        getAllRows("lp_ready_log").catch(() => []),
        getAllRows("ceo_reject_log").catch(() => []),
      ]);

    // Unique run_ids (most recent first)
    const runIds = [...new Set(snapshots.map((s) => s.run_id).filter(Boolean))].reverse();

    const runs = runIds.slice(0, 20).map((rid) => {
      const snapshot = snapshots.find((s) => s.run_id === rid);
      const timestamp = snapshot?.timestamp || "";

      // Layer 1: count from business_model_types
      const types = typeRows.filter((t) => t.run_id === rid);

      // Layer 2: count from business_combos
      const combos = comboRows.filter((c) => c.run_id === rid);

      // Phase C: demand verification
      const demands = demandRows.filter((d) => d.run_id === rid);
      const demandPass = demands.filter((d) => d.verdict === "PASS" || d.verdict === "STRONG").length;

      // Phase D: gate results
      const gates = gateRows.filter((g) => g.run_id === rid);
      const gatePass = gates.filter((g) => g.status === "PASS").length;
      const gateFail = gates.filter((g) => g.status === "FAIL").length;

      // Phase E: offers
      const offers = offerRows.filter((o) => o.run_id === rid);

      // Phase F: LP ready
      const lp = lpReady.find((r) => r.run_id === rid);

      // Phase G: CEO decision
      const ceoDecision = ceoLog.find(
        (r) => r.run_id === rid && (r.type === "run_approve" || r.type === "run_reject"),
      );

      // Build step array
      const steps = [
        {
          name: "Layer 1 (事業モデル型)",
          status: types.length > 0 ? "OK" : "SKIP",
          count: types.length,
          errors: [] as string[],
        },
        {
          name: "Layer 2 (コンボ生成)",
          status: combos.length > 0 ? "OK" : "SKIP",
          count: combos.length,
          errors: [] as string[],
        },
        {
          name: "Phase C (証拠収集)",
          status: demands.length > 0 ? (demandPass > 0 ? "OK" : "FAIL") : "SKIP",
          count: demandPass,
          errors: demands.filter((d) => d.verdict === "FAIL").map((d) => d.fail_reason || "FAIL"),
        },
        {
          name: "Phase D (競合分析)",
          status: gateFail > 0 && gatePass === 0 ? "FAIL" : gatePass > 0 ? "OK" : "SKIP",
          count: gatePass,
          errors: gates.filter((g) => g.status === "FAIL").map((g) => g.fail_reason || "FAIL"),
        },
        {
          name: "Phase E (オファー生成)",
          status: offers.length > 0 ? "OK" : "SKIP",
          count: offers.length,
          errors: [] as string[],
        },
        {
          name: "Phase F (LP生成)",
          status: lp?.status === "READY" ? "OK" : lp ? "FAIL" : "SKIP",
          count: lp?.status === "READY" ? 1 : 0,
          errors: lp && lp.status !== "READY" ? [lp.status || "不明"] : [],
        },
        {
          name: "Phase G (承認)",
          status: ceoDecision
            ? ceoDecision.type === "run_approve" ? "OK" : "FAIL"
            : lp?.status === "READY" ? "running" : "SKIP",
          count: ceoDecision ? 1 : 0,
          errors: ceoDecision?.type === "run_reject" ? ["CEO STOP"] : [],
        },
      ];

      // Filter stats from actual sheet data
      const filterStats = {
        layer1_generated: types.length,
        layer1_passed: types.filter((t) => t.review_pass !== "False").length,
        layer2_generated: combos.length,
        layer2_passed: combos.length,
      };

      return {
        run_id: rid,
        timestamp,
        steps,
        filterStats,
      };
    });

    return NextResponse.json({ runs });
  } catch (err) {
    console.error("[explore] GET Error:", err);
    return NextResponse.json({ runs: [], error: String(err) }, { status: 500 });
  }
}
