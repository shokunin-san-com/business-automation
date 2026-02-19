import { NextResponse } from "next/server";
import { getAllRows } from "@/lib/sheets";

/**
 * GET /api/analytics
 * Fetches analytics and improvement_suggestions from Google Sheets directly.
 */
export async function GET() {
  try {
    const [entries, rawSuggestions] = await Promise.all([
      getAllRows("analytics").catch(() => []),
      getAllRows("improvement_suggestions").catch(() => []),
    ]);

    const suggestions = rawSuggestions.map((s) => ({
      business_id: s.business_id || "",
      text: s.suggestion_text || s.text || "",
      priority: s.priority || "low",
      date: s.suggested_at || s.date || "",
    }));

    // Compute summary
    const totalPageviews = entries.reduce((sum, e) => sum + (Number(e.pageviews) || 0), 0);
    const totalSessions = entries.reduce((sum, e) => sum + (Number(e.sessions) || 0), 0);
    const totalConversions = entries.reduce((sum, e) => sum + (Number(e.conversions) || 0), 0);
    const bounceRates = entries.filter((e) => e.bounce_rate).map((e) => Number(e.bounce_rate));
    const avgBounceRate =
      bounceRates.length > 0
        ? bounceRates.reduce((a, b) => a + b, 0) / bounceRates.length
        : 0;

    return NextResponse.json({
      entries,
      suggestions,
      summary: { totalPageviews, totalSessions, totalConversions, avgBounceRate },
    });
  } catch {
    // Return empty data if Sheets not configured yet
    return NextResponse.json({
      entries: [],
      suggestions: [],
      summary: { totalPageviews: 0, totalSessions: 0, totalConversions: 0, avgBounceRate: 0 },
    });
  }
}
