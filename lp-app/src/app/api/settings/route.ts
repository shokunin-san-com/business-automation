import { NextRequest, NextResponse } from "next/server";
import { getAllRows, updateCell } from "@/lib/sheets";

/** Default settings used when Google Sheets is unavailable */
const DEFAULT_SETTINGS = [
  { key: "target_industries", value: "IT,\u30A8\u30CD\u30EB\u30AE\u30FC,\u30D8\u30EB\u30B9\u30B1\u30A2" },
  { key: "trend_keywords", value: "AI,DX,\u30B5\u30B9\u30C6\u30CA\u30D3\u30EA\u30C6\u30A3" },
  { key: "ideas_per_run", value: "3" },
  { key: "form_sales_per_day", value: "10" },
  { key: "lp_base_url", value: "https://example.com" },
  { key: "slack_notification", value: "enabled" },
  { key: "auto_approve", value: "disabled" },
  { key: "risk_threshold", value: "medium" },
];

/**
 * GET /api/settings — Read settings from Google Sheets
 */
export async function GET() {
  try {
    const rows = await getAllRows("settings");
    if (rows.length > 0) {
      const settings = rows.map((r) => ({
        key: r.key || "",
        value: r.value || "",
      }));
      return NextResponse.json({ settings, source: "sheets" });
    }
  } catch {
    /* Google Sheets unavailable, fall through */
  }

  // Fallback: defaults
  return NextResponse.json({ settings: DEFAULT_SETTINGS, source: "default" });
}

/**
 * POST /api/settings — Save settings to Google Sheets
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const settings: { key: string; value: string }[] = body.settings || [];

    if (settings.length === 0) {
      return NextResponse.json({ error: "No settings provided" }, { status: 400 });
    }

    let sheetsOk = false;
    try {
      for (const s of settings) {
        await updateCell("settings", "key", s.key, "value", s.value);
      }
      sheetsOk = true;
    } catch {
      /* Sheets unavailable */
    }

    return NextResponse.json({ ok: true, saved_to: sheetsOk ? "sheets" : "failed" });
  } catch (err) {
    console.error("Settings update error:", err);
    return NextResponse.json({ ok: false, error: "Failed to update" }, { status: 500 });
  }
}
