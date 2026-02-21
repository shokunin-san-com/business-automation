import { NextRequest, NextResponse } from "next/server";
import { appendRows, ensureSheetExists, getAllRows, updateCell } from "@/lib/sheets";

const LEARNING_MEMORY_HEADERS = [
  "id", "type", "source", "category", "content",
  "context_json", "confidence", "priority", "status",
  "applied_count", "created_at", "expires_at",
];

function generateId(): string {
  const hex = Array.from(crypto.getRandomValues(new Uint8Array(4)))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return `sug_${hex}`;
}

/**
 * POST /api/analytics/suggestions
 *
 * Accept or dismiss an AI improvement suggestion.
 * Body: { text: string, priority: string, business_id: string, action: "accept" | "dismiss" }
 *
 * - accept: saves the suggestion as a directive in learning_memory
 * - dismiss: marks the suggestion as dismissed in improvement_suggestions sheet
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { text, priority, business_id, action } = body;

    if (!text || !action || !["accept", "dismiss"].includes(action)) {
      return NextResponse.json(
        { error: "text and action (accept|dismiss) are required" },
        { status: 400 },
      );
    }

    if (action === "accept") {
      // Save as directive in learning_memory
      await ensureSheetExists("learning_memory", LEARNING_MEMORY_HEADERS);

      const now = new Date().toISOString().replace("T", " ").substring(0, 16);
      const id = generateId();

      // Infer category from business_id or content
      const category = inferCategory(text, business_id || "");

      await appendRows("learning_memory", [[
        id, "directive", "suggestion_promotion", category,
        text, JSON.stringify({ business_id, priority }), "0.8", priority || "medium",
        "active", "0", now, "",
      ]]);

      // Mark suggestion as applied in improvement_suggestions
      await markSuggestionStatus(text, "applied");

      return NextResponse.json({ ok: true, action: "accepted", id, category });
    }

    // action === "dismiss"
    await markSuggestionStatus(text, "dismissed");

    return NextResponse.json({ ok: true, action: "dismissed" });
  } catch (err) {
    console.error("Suggestion action error:", err);
    return NextResponse.json(
      { error: "Failed to process suggestion" },
      { status: 500 },
    );
  }
}

/**
 * Infer a directive category from the suggestion text / business_id.
 */
function inferCategory(text: string, businessId: string): string {
  const t = (text + " " + businessId).toLowerCase();
  if (t.includes("lp") || t.includes("ランディング") || t.includes("ページ")) return "lp_optimization";
  if (t.includes("sns") || t.includes("twitter") || t.includes("投稿")) return "sns_strategy";
  if (t.includes("フォーム") || t.includes("営業") || t.includes("メール")) return "form_sales";
  if (t.includes("事業") || t.includes("アイデア") || t.includes("市場")) return "idea_generation";
  return "general";
}

/**
 * Try to mark a suggestion in the improvement_suggestions sheet by matching its text.
 */
async function markSuggestionStatus(text: string, status: string): Promise<void> {
  try {
    const rows = await getAllRows("improvement_suggestions");
    const match = rows.find(
      (r) => (r.suggestion_text || r.text || "") === text,
    );
    if (match && match.id) {
      await updateCell("improvement_suggestions", "id", match.id, "status", status);
    }
  } catch {
    // Non-critical — suggestion sheet may not have status column yet
    console.warn("Could not update suggestion status (column may not exist)");
  }
}
