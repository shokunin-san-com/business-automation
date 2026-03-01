import { NextResponse } from "next/server";
import { getAllRows } from "@/lib/sheets";

/**
 * GET /api/offers
 *
 * Returns all offers with aggregated stats (email, inquiry, rank).
 *
 * Data sources:
 *   - offer_3_log        -> base offer data
 *   - gate_decision_log  -> market/payer info
 *   - mail_sent_log      -> email sent/replied counts
 *   - inquiry_log        -> inquiry counts
 *   - lp_ready_log       -> LP readiness
 *   - ceo_reject_log     -> CEO decisions (GO/STOP/rejected)
 */
export async function GET() {
  try {
    const offerRows = await getAllRows("offer_3_log").catch(() => []);
    const gateRows = await getAllRows("gate_decision_log").catch(() => []);
    const mailRows = await getAllRows("mail_sent_log").catch(() => []);
    const inquiryRows = await getAllRows("inquiry_log").catch(() => []);
    const lpReady = await getAllRows("lp_ready_log").catch(() => []);
    const ceoLog = await getAllRows("ceo_reject_log").catch(() => []);

    // Build lookup maps
    const readyRunIds = new Set(
      lpReady.filter((r) => r.status === "READY").map((r) => r.run_id),
    );

    // CEO decisions per run
    const ceoDecisions = new Map<string, string>();
    for (const row of ceoLog) {
      if (row.type === "run_approve") ceoDecisions.set(row.run_id, "GO");
      if (row.type === "run_reject") ceoDecisions.set(row.run_id, "STOP");
    }

    // Rejected individual offers
    const rejectedOffers = new Set(
      ceoLog
        .filter((r) => r.type === "offer")
        .map((r) => `${r.run_id}:${r.rejected_item}`),
    );

    const offers = offerRows.map((o) => {
      const rid = o.run_id || "";
      const gate = gateRows.find((g) => g.run_id === rid && g.status === "PASS");

      const emailSent = mailRows.filter(
        (m) => (m.run_id === rid || m.business_id === rid) && m.status === "sent",
      ).length;
      const emailReplied = mailRows.filter(
        (m) => (m.run_id === rid || m.business_id === rid) && m.status === "replied",
      ).length;
      const inquiries = inquiryRows.filter(
        (m) => m.run_id === rid || m.business_id === rid,
      ).length;

      // Determine status
      let status = "pending_approval";
      const ceoDecision = ceoDecisions.get(rid);
      if (rejectedOffers.has(`${rid}:${o.offer_name}`)) {
        status = "rejected";
      } else if (ceoDecision === "STOP") {
        status = "stopped";
      } else if (ceoDecision === "GO" && readyRunIds.has(rid)) {
        status = "active";
      } else if (readyRunIds.has(rid)) {
        status = "pending_approval";
      }

      // Determine rank based on activity
      let rank = "D";
      if (inquiries > 0) rank = "A";
      else if (emailReplied > 0) rank = "B";
      else if (emailSent > 0) rank = "C";

      // Elapsed days since gate passed
      let elapsedDays = 0;
      if (gate?.timestamp) {
        const gateDate = new Date(gate.timestamp);
        const now = new Date();
        elapsedDays = Math.floor((now.getTime() - gateDate.getTime()) / (1000 * 60 * 60 * 24));
      }

      return {
        runId: rid,
        offerName: o.offer_name || "",
        target: gate?.payer || o.payer || "",
        price: o.price || "",
        rank,
        emailSent,
        emailReplied,
        inquiries,
        elapsedDays,
        status,
        lpUrl: readyRunIds.has(rid)
          ? `https://shokunin-san.xyz/lp/${encodeURIComponent(rid)}`
          : "",
      };
    });

    return NextResponse.json({ offers });
  } catch (err) {
    console.error("[offers] GET Error:", err);
    return NextResponse.json({ offers: [], error: String(err) }, { status: 500 });
  }
}
