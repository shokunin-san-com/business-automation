import { NextResponse } from "next/server";
import { getAllRows } from "@/lib/sheets";

/**
 * GET /api/explore
 *
 * Returns pipeline run history with per-step progress and filter stats.
 *
 * Data sources:
 *   - settings_snapshot   -> run_id list
 *   - pipeline_status     -> step-level status/metrics
 *   - gate_decision_log   -> Phase D results
 *   - offer_3_log         -> Phase E results
 *   - lp_ready_log        -> Phase F results
 *   - ceo_reject_log      -> approval status
 */
export async function GET() {
  try {
    const snapshots = await getAllRows("settings_snapshot").catch(() => []);
    const pipelineRows = await getAllRows("pipeline_status").catch(() => []);
    const gateRows = await getAllRows("gate_decision_log").catch(() => []);
    const offerRows = await getAllRows("offer_3_log").catch(() => []);
    const lpReady = await getAllRows("lp_ready_log").catch(() => []);
    const ceoLog = await getAllRows("ceo_reject_log").catch(() => []);

    // Unique run_ids (most recent first)
    const runIds = [...new Set(snapshots.map((s) => s.run_id).filter(Boolean))].reverse();

    const runs = runIds.slice(0, 20).map((rid) => {
      const snapshot = snapshots.find((s) => s.run_id === rid);
      const timestamp = snapshot?.timestamp || "";

      // Per-step info from pipeline_status
      const latestPipeline = pipelineRows.find((r) => r.script_name === "orchestrate_v2");
      let metricsJson: Record<string, unknown> = {};
      if (latestPipeline?.metrics_json) {
        try { metricsJson = JSON.parse(latestPipeline.metrics_json); } catch { /* ignore */ }
      }

      // Gate results for this run
      const gates = gateRows.filter((g) => g.run_id === rid);
      const gatePass = gates.filter((g) => g.status === "PASS").length;
      const gateFail = gates.filter((g) => g.status === "FAIL").length;

      // Offers for this run
      const offers = offerRows.filter((o) => o.run_id === rid);

      // LP ready
      const lp = lpReady.find((r) => r.run_id === rid);

      // CEO decision
      const ceoDecision = ceoLog.find(
        (r) => r.run_id === rid && (r.type === "run_approve" || r.type === "run_reject"),
      );

      // Build step array
      const steps = [
        {
          name: "Layer 1 (事業モデル型)",
          status: getStepStatus(metricsJson, "layer1"),
          count: Number(metricsJson.layer1_types_generated || 0),
          errors: [] as string[],
        },
        {
          name: "Layer 2 (コンボ生成)",
          status: getStepStatus(metricsJson, "layer2"),
          count: Number(metricsJson.layer2_combos_generated || 0),
          errors: [] as string[],
        },
        {
          name: "Phase C (証拠収集)",
          status: gates.length > 0 ? "OK" : "SKIP",
          count: gates.length,
          errors: [] as string[],
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

      // Filter stats (from metrics_json if available, otherwise from counts)
      const filterStats = {
        layer1_generated: Number(metricsJson.layer1_types_generated || 0),
        layer1_passed: Number(metricsJson.layer1_types_passed || metricsJson.layer1_types_generated || 0),
        layer2_generated: Number(metricsJson.layer2_combos_generated || 0),
        layer2_passed: Number(metricsJson.layer2_combos_passed || metricsJson.layer2_combos_generated || 0),
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

function getStepStatus(metrics: Record<string, unknown>, layer: string): string {
  const generated = Number(metrics[`${layer}_types_generated`] || metrics[`${layer}_combos_generated`] || 0);
  if (generated > 0) return "OK";
  return "SKIP";
}
