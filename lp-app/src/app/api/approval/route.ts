import { NextRequest, NextResponse } from "next/server";
import { getAllRows, appendRows } from "@/lib/sheets";

/**
 * GET /api/approval
 *
 * Returns approval items: runs that have completed LP generation and are
 * awaiting CEO GO/STOP decision.
 *
 * Data sources:
 *   - lp_ready_log (status=READY → candidate runs)
 *   - ceo_reject_log (type=run_approve / run_reject → already decided)
 *   - offer_3_log (offer details for each run)
 *   - mail_sent_log (draft email for preview)
 */
export async function GET() {
  try {
    const lpReady = await getAllRows("lp_ready_log").catch(() => []);
    const ceoLog = await getAllRows("ceo_reject_log").catch(() => []);
    const offers = await getAllRows("offer_3_log").catch(() => []);
    const mailDrafts = await getAllRows("mail_sent_log").catch(() => []);

    // Build decision map: run_id -> { decision, decided_at }
    const decisionMap = new Map<string, { decision: string; decided_at: string }>();
    for (const row of ceoLog) {
      if (row.type === "run_approve" || row.type === "run_reject") {
        decisionMap.set(row.run_id, {
          decision: row.type === "run_approve" ? "GO" : "STOP",
          decided_at: row.timestamp || "",
        });
      }
    }

    // Build items from READY runs
    const readyRuns = lpReady.filter((r) => r.status === "READY");
    const items = readyRuns.map((run) => {
      const rid = run.run_id || "";
      const runOffers = offers.filter((o) => o.run_id === rid);
      const mainOffer = runOffers[0] || {};

      // Find draft email for this run (first unsent or latest)
      const runMails = mailDrafts.filter(
        (m) => (m.run_id === rid || m.business_id === rid) && m.email_subject,
      );
      const draftMail = runMails[runMails.length - 1] || {};

      const decision = decisionMap.get(rid);

      return {
        run_id: rid,
        offer_name: mainOffer.offer_name || rid.slice(0, 8),
        lp_url: run.lp_url || "",
        email_subject: draftMail.email_subject || "",
        email_body: draftMail.email_body || "",
        ceo_decision: decision?.decision || "",
        decided_at: decision?.decided_at || "",
      };
    });

    // Sort: pending first, then by timestamp desc
    items.sort((a, b) => {
      if (!a.ceo_decision && b.ceo_decision) return -1;
      if (a.ceo_decision && !b.ceo_decision) return 1;
      return 0;
    });

    return NextResponse.json({ items });
  } catch (err) {
    console.error("[approval] GET Error:", err);
    return NextResponse.json({ items: [], error: String(err) }, { status: 500 });
  }
}

/**
 * POST /api/approval
 *
 * Record CEO GO/STOP decision for a run.
 *
 * Body: { run_id: string, decision: "GO" | "STOP" }
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { run_id, decision } = body;

    if (!run_id || !decision) {
      return NextResponse.json(
        { error: "run_id and decision are required" },
        { status: 400 },
      );
    }

    if (decision !== "GO" && decision !== "STOP") {
      return NextResponse.json(
        { error: "decision must be 'GO' or 'STOP'" },
        { status: 400 },
      );
    }

    const now = new Date().toISOString().slice(0, 16).replace("T", " ");
    const type = decision === "GO" ? "run_approve" : "run_reject";

    await appendRows("ceo_reject_log", [
      [run_id, type, "", decision === "STOP" ? "CEO STOP" : "", "CEO", now],
    ]);

    return NextResponse.json({ ok: true, run_id, decision });
  } catch (err) {
    console.error("[approval] POST Error:", err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
