import { NextRequest, NextResponse } from "next/server";
import { getAllRows, appendRows } from "@/lib/sheets";

/**
 * POST /api/inquiry — Record a new LP inquiry
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const {
      business_id,
      company_name,
      contact_name,
      contact_email,
      message,
      source_lp_url,
      run_id,
    } = body;

    if (!business_id || !contact_email) {
      return NextResponse.json(
        { error: "business_id and contact_email are required" },
        { status: 400 },
      );
    }

    const inquiryId = `inq_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const timestamp = new Date().toISOString();

    await appendRows("inquiry_log", [
      [
        inquiryId,
        run_id || "",
        business_id,
        timestamp,
        company_name || "",
        contact_name || "",
        contact_email,
        message || "",
        source_lp_url || "",
        "new",
        "",
      ],
    ]);

    // Send Slack / Google Chat notification for new inquiry
    try {
      const notifyText =
        `🔔 *新規お問い合わせ*\n` +
        `事業: ${business_id}\n` +
        `会社: ${company_name || "未記入"}\n` +
        `担当者: ${contact_name || "未記入"}\n` +
        `メール: ${contact_email}\n` +
        `経路: ${source_lp_url || "不明"}\n` +
        `メッセージ: ${(message || "").slice(0, 100)}`;

      const webhooks = [
        process.env.SLACK_WEBHOOK_URL,
        process.env.GCHAT_WEBHOOK_URL,
      ].filter(Boolean);

      await Promise.allSettled(
        webhooks.map((url) =>
          fetch(url!, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: notifyText }),
          }),
        ),
      );
    } catch {
      // Non-critical: don't fail the inquiry recording
    }

    return NextResponse.json({ ok: true, inquiry_id: inquiryId });
  } catch (err) {
    console.error("Inquiry POST error:", err);
    return NextResponse.json(
      { ok: false, error: "Failed to record inquiry" },
      { status: 500 },
    );
  }
}

/**
 * GET /api/inquiry — List inquiries with optional filters
 * ?business_id=xxx&status=new
 */
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const businessId = searchParams.get("business_id");
    const status = searchParams.get("status");

    let rows = await getAllRows("inquiry_log");

    if (businessId) {
      rows = rows.filter((r) => r.business_id === businessId);
    }
    if (status) {
      rows = rows.filter((r) => r.status === status);
    }

    return NextResponse.json({ inquiries: rows, total: rows.length });
  } catch (err) {
    console.error("Inquiry GET error:", err);
    return NextResponse.json({ inquiries: [], total: 0, error: String(err) });
  }
}
