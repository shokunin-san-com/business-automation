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
