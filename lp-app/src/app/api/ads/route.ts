import { NextRequest, NextResponse } from "next/server";
import { getAllRows, updateCell, ensureSheetExists } from "@/lib/sheets";

const ADS_HEADERS = [
  "id", "business_id", "campaign_name", "campaign_id", "status",
  "daily_budget", "keywords_json", "ad_texts_json",
  "created_at", "activated_at", "performance_json",
];

/**
 * GET /api/ads
 * Returns pending ad campaigns awaiting approval.
 */
export async function GET() {
  try {
    await ensureSheetExists("ads_campaigns", ADS_HEADERS);
    const rows = await getAllRows("ads_campaigns");

    const pending = rows
      .filter((r) => r.status === "pending")
      .map((r) => {
        let keywords: string[] = [];
        let adTexts: { headlines: string[]; descriptions: string[] } = {
          headlines: [],
          descriptions: [],
        };

        try {
          keywords = JSON.parse(r.keywords_json || "[]");
        } catch { /* ignore */ }
        try {
          adTexts = JSON.parse(r.ad_texts_json || "{}");
        } catch { /* ignore */ }

        return {
          id: r.id || "",
          businessId: r.business_id || "",
          campaignName: r.campaign_name || "",
          campaignId: r.campaign_id || "",
          dailyBudget: parseInt(r.daily_budget) || 0,
          keywords,
          headlines: adTexts.headlines || [],
          descriptions: adTexts.descriptions || [],
          createdAt: r.created_at || "",
        };
      });

    return NextResponse.json({ campaigns: pending });
  } catch (err) {
    console.error("Ads GET error:", err);
    return NextResponse.json({ campaigns: [] });
  }
}

/**
 * POST /api/ads
 * Body: { id: string, action: "approve" | "reject" }
 * Approve or reject a pending ad campaign.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { id, action } = body as { id: string; action: "approve" | "reject" };

    if (!id || !["approve", "reject"].includes(action)) {
      return NextResponse.json({ error: "Invalid request" }, { status: 400 });
    }

    await ensureSheetExists("ads_campaigns", ADS_HEADERS);

    if (action === "reject") {
      const updated = await updateCell("ads_campaigns", "id", id, "status", "rejected");
      if (!updated) {
        return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
      }
      return NextResponse.json({ ok: true, status: "rejected" });
    }

    // Approve: activate campaign via Google Ads API
    // First get the campaign_id from sheet
    const rows = await getAllRows("ads_campaigns");
    const campaign = rows.find((r) => r.id === id);

    if (!campaign) {
      return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
    }

    // Note: In production, this would call the Google Ads API to enable the campaign.
    // For now, we update the sheet status. The actual activation happens via the Python
    // google_ads_client.activate_campaign() which can be triggered separately.
    await updateCell("ads_campaigns", "id", id, "status", "active");
    await updateCell(
      "ads_campaigns",
      "id",
      id,
      "activated_at",
      new Date().toISOString(),
    );

    return NextResponse.json({
      ok: true,
      status: "active",
      campaignId: campaign.campaign_id,
    });
  } catch (err) {
    console.error("Ads POST error:", err);
    return NextResponse.json({ error: "Internal error" }, { status: 500 });
  }
}
