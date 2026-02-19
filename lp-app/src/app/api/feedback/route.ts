import { NextRequest, NextResponse } from "next/server";
import { getAllRows, ensureSheetExists, updateCell } from "@/lib/sheets";

const LEARNING_HEADERS = [
  "id", "type", "source", "category", "content",
  "context_json", "confidence", "priority", "status",
  "applied_count", "created_at", "expires_at",
];

/**
 * GET /api/feedback
 * Returns active learning memories.
 */
export async function GET() {
  try {
    await ensureSheetExists("learning_memory", LEARNING_HEADERS);
    const rows = await getAllRows("learning_memory");

    const memories = rows
      .filter((r) => r.status === "active")
      .map((r) => ({
        id: r.id || "",
        type: r.type || "",
        source: r.source || "",
        category: r.category || "",
        content: r.content || "",
        confidence: parseFloat(r.confidence) || 0,
        priority: r.priority || "medium",
        status: r.status || "",
        appliedCount: parseInt(r.applied_count) || 0,
        createdAt: r.created_at || "",
        expiresAt: r.expires_at || "",
      }));

    // Sort: directives first, then by priority
    const priorityOrder: Record<string, number> = { high: 0, medium: 1, low: 2 };
    memories.sort((a, b) => {
      if (a.type === "directive" && b.type !== "directive") return -1;
      if (a.type !== "directive" && b.type === "directive") return 1;
      return (priorityOrder[a.priority] ?? 1) - (priorityOrder[b.priority] ?? 1);
    });

    // Also fetch performance summary
    let performanceSummary: {
      businessId: string;
      latestScore: number;
      avgScore: number;
      latestPV: number;
      latestCVR: number;
    }[] = [];

    try {
      await ensureSheetExists("performance_log", [
        "id", "business_id", "date", "lp_pageviews", "lp_sessions",
        "lp_bounce_rate", "lp_avg_time", "lp_conversions",
        "sns_posts_count", "form_submissions", "form_responses",
        "performance_score", "created_at",
      ]);
      const perfRows = await getAllRows("performance_log");
      const cutoff = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000)
        .toISOString()
        .split("T")[0];
      const recent = perfRows.filter((r) => String(r.date || "") >= cutoff);

      const byBid: Record<string, typeof recent> = {};
      for (const r of recent) {
        const bid = String(r.business_id || "");
        if (!byBid[bid]) byBid[bid] = [];
        byBid[bid].push(r);
      }

      performanceSummary = Object.entries(byBid).map(([bid, records]) => {
        const latest = records[records.length - 1];
        const avgScore =
          records.reduce((s, r) => s + Number(r.performance_score || 0), 0) /
          records.length;
        return {
          businessId: bid,
          latestScore: Number(latest.performance_score || 0),
          avgScore: Math.round(avgScore),
          latestPV: Number(latest.lp_pageviews || 0),
          latestCVR: Number(latest.lp_conversions || 0),
        };
      });
    } catch { /* ignore */ }

    return NextResponse.json({ memories, performanceSummary });
  } catch (err) {
    console.error("Feedback GET error:", err);
    return NextResponse.json({ memories: [], performanceSummary: [] });
  }
}

/**
 * DELETE /api/feedback?id=xxx
 * Supersede a learning memory (set status to 'superseded').
 */
export async function DELETE(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const id = searchParams.get("id");

    if (!id) {
      return NextResponse.json({ error: "id required" }, { status: 400 });
    }

    await ensureSheetExists("learning_memory", LEARNING_HEADERS);

    const updated = await updateCell(
      "learning_memory",
      "id",
      id,
      "status",
      "superseded",
    );

    if (!updated) {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    }

    return NextResponse.json({ ok: true, id });
  } catch (err) {
    console.error("Feedback DELETE error:", err);
    return NextResponse.json({ error: "Internal error" }, { status: 500 });
  }
}
