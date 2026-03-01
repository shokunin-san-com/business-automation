import { NextRequest, NextResponse } from "next/server";
import { getAllRows, appendRows, batchUpdateColumn } from "@/lib/sheets";

/**
 * POST /api/admin/v4-cleanup
 *
 * Performs v4 data cleanup operations:
 *   - reject_offers:  Reject all offers containing prohibited terms
 *   - unpublish_blogs: Set all blog articles to "unpublished"
 *   - all: Both operations
 *
 * Body: { action: "reject_offers" | "reject_all_offers" | "unpublish_blogs" | "all" }
 */

const PROHIBITED_TERMS = [
  "AI", "人工知能", "機械学習", "SaaS", "プラットフォーム",
  "最適化", "効率化", "ソリューション", "DX推進", "DX",
  "3D", "AR", "VR", "BIM", "CAD", "ドローン", "IoT",
  "クラウド", "アプリ", "マッチング", "サブスク",
];

function containsProhibited(offer: Record<string, string>): string[] {
  const text = [
    offer.offer_name || "",
    offer.deliverable || "",
    offer.payer || "",
  ].join(" ");

  return PROHIBITED_TERMS.filter((term) => text.includes(term));
}

/**
 * GET /api/admin/v4-cleanup
 *
 * Pipeline diagnostics: budget check, settings, recent run summary
 */
export async function GET() {
  try {
    const [costRows, settingsRows, pipelineRows, snapshots] = await Promise.all([
      getAllRows("cost_tracking").catch(() => []),
      getAllRows("settings").catch(() => []),
      getAllRows("pipeline_status").catch(() => []),
      getAllRows("settings_snapshot").catch(() => []),
    ]);

    // Monthly cost calculation (current month)
    const now = new Date();
    const monthPrefix = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
    let monthlyCostJpy = 0;
    for (const row of costRows) {
      const ts = row.timestamp || "";
      if (ts.startsWith(monthPrefix)) {
        monthlyCostJpy += parseFloat(row.cost_jpy || "0") || 0;
      }
    }

    // Budget settings
    const settingsMap = new Map(settingsRows.map((r) => [r.key, r.value]));
    const warnJpy = parseFloat(settingsMap.get("cost_warn_jpy") || "25000");
    const hardStopJpy = parseFloat(settingsMap.get("cost_hard_stop_jpy") || "30000");

    // Pipeline status
    const orchestrateStatus = pipelineRows.find((r) => r.script_name === "orchestrate_v2");

    // Recent runs (last 5)
    const recentRuns = snapshots.slice(-5).reverse().map((s) => ({
      run_id: s.run_id?.slice(0, 8),
      timestamp: s.timestamp,
    }));

    return NextResponse.json({
      budget: {
        monthly_cost_jpy: Math.round(monthlyCostJpy),
        warn_jpy: warnJpy,
        hard_stop_jpy: hardStopJpy,
        status: monthlyCostJpy >= hardStopJpy ? "HARD_STOP" : monthlyCostJpy >= warnJpy ? "WARNING" : "OK",
        month: monthPrefix,
        total_cost_rows: costRows.length,
      },
      pipeline: orchestrateStatus ? {
        status: orchestrateStatus.status,
        detail: orchestrateStatus.detail,
        timestamp: orchestrateStatus.timestamp,
        metrics_json: orchestrateStatus.metrics_json,
      } : null,
      recent_runs: recentRuns,
      key_settings: {
        ceo_profile_json: settingsMap.get("ceo_profile_json")?.slice(0, 100) || "(not set)",
        v2_continuous_mode: settingsMap.get("v2_continuous_mode") || "(not set)",
        v2_continuous_count: settingsMap.get("v2_continuous_count") || "(not set)",
        max_sv_combos: settingsMap.get("max_sv_combos") || "(not set)",
        max_competitor_combos: settingsMap.get("max_competitor_combos") || "(not set)",
      },
    });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const action = body.action || "all";
    const now = new Date().toISOString().slice(0, 16).replace("T", " ");
    const report: Record<string, unknown> = {};

    // --- Task 2: Reject old offers with prohibited terms ---
    if (action === "reject_offers" || action === "all") {
      const offerRows = await getAllRows("offer_3_log");
      const ceoLog = await getAllRows("ceo_reject_log");

      // Already rejected offers
      const alreadyRejected = new Set(
        ceoLog
          .filter((r) => r.type === "offer")
          .map((r) => `${r.run_id}:${r.rejected_item}`),
      );

      const toReject: string[][] = [];
      const details: { run_id: string; offer_name: string; violations: string[] }[] = [];

      for (const offer of offerRows) {
        const rid = offer.run_id || "";
        const name = offer.offer_name || "";
        const key = `${rid}:${name}`;

        if (alreadyRejected.has(key)) continue;

        const violations = containsProhibited(offer);
        if (violations.length > 0) {
          toReject.push([
            rid,
            "offer",
            name,
            `v4自動却下: 禁止語[${violations.join(",")}]`,
            "SYSTEM",
            now,
          ]);
          details.push({ run_id: rid, offer_name: name, violations });
        }
      }

      if (toReject.length > 0) {
        await appendRows("ceo_reject_log", toReject);
      }

      report.reject_offers = {
        total_offers: offerRows.length,
        already_rejected: alreadyRejected.size,
        newly_rejected: toReject.length,
        details,
      };
    }

    // --- Reject ALL remaining offers (regardless of prohibited terms) ---
    if (action === "reject_all_offers") {
      const offerRows = await getAllRows("offer_3_log");
      const ceoLog = await getAllRows("ceo_reject_log");

      const alreadyRejected = new Set(
        ceoLog
          .filter((r) => r.type === "offer")
          .map((r) => `${r.run_id}:${r.rejected_item}`),
      );

      const toReject: string[][] = [];
      const details: { run_id: string; offer_name: string }[] = [];

      for (const offer of offerRows) {
        const rid = offer.run_id || "";
        const name = offer.offer_name || "";
        const key = `${rid}:${name}`;

        if (alreadyRejected.has(key)) continue;

        toReject.push([
          rid,
          "offer",
          name,
          "v4全却下: 旧オファー一括reject",
          "SYSTEM",
          now,
        ]);
        details.push({ run_id: rid, offer_name: name });
      }

      if (toReject.length > 0) {
        await appendRows("ceo_reject_log", toReject);
      }

      report.reject_all_offers = {
        total_offers: offerRows.length,
        already_rejected: alreadyRejected.size,
        newly_rejected: toReject.length,
        details,
      };
    }

    // --- Task 4: Unpublish all blog articles ---
    if (action === "unpublish_blogs" || action === "all") {
      const count = await batchUpdateColumn(
        "blog_articles",
        "status",
        "unpublished",
        (row) => row.status === "published" || row.status === "draft",
      );

      report.unpublish_blogs = {
        updated: count,
      };
    }

    return NextResponse.json({ ok: true, report });
  } catch (err) {
    console.error("[admin/v4-cleanup] Error:", err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
