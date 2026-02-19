import { NextRequest } from "next/server";
import { getAllRows, appendRows, ensureSheetExists } from "@/lib/sheets";
import Anthropic from "@anthropic-ai/sdk";
import { GoogleGenerativeAI } from "@google/generative-ai";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generateId(): string {
  const hex = Array.from(crypto.getRandomValues(new Uint8Array(4)))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return `dir_${hex}`;
}

async function buildSystemPrompt(): Promise<string> {
  // 1. Performance summary (last 7 days)
  let performanceSummary = "";
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
    const recent = perfRows.filter(
      (r) => String(r.date || "") >= cutoff
    );

    if (recent.length > 0) {
      // Group by business_id
      const byBid: Record<string, typeof recent> = {};
      for (const r of recent) {
        const bid = String(r.business_id || "");
        if (!byBid[bid]) byBid[bid] = [];
        byBid[bid].push(r);
      }

      const parts: string[] = [];
      for (const [bid, records] of Object.entries(byBid)) {
        const latest = records[records.length - 1];
        const avgScore =
          records.reduce((s, r) => s + Number(r.performance_score || 0), 0) /
          records.length;
        parts.push(
          `- ${bid}: スコア${latest.performance_score}/100 (平均${avgScore.toFixed(0)}), ` +
          `PV${latest.lp_pageviews}, セッション${latest.lp_sessions}, ` +
          `CVR${latest.lp_conversions}, 直帰率${latest.lp_bounce_rate}%, ` +
          `SNS${latest.sns_posts_count}件, フォーム${latest.form_submissions}件`
        );
      }
      performanceSummary = parts.join("\n");
    }
  } catch { /* ignore */ }

  // 2. Active learning memories
  let learningMemory = "";
  try {
    await ensureSheetExists("learning_memory", [
      "id", "type", "source", "category", "content",
      "context_json", "confidence", "priority", "status",
      "applied_count", "created_at", "expires_at",
    ]);
    const memRows = await getAllRows("learning_memory");
    const active = memRows.filter((r) => r.status === "active");
    const sorted = active.sort((a, b) => {
      const po: Record<string, number> = { high: 0, medium: 1, low: 2 };
      return (po[a.priority] ?? 1) - (po[b.priority] ?? 1);
    });

    if (sorted.length > 0) {
      learningMemory = sorted
        .slice(0, 10)
        .map((r) => {
          const src = r.source === "human_chat" ? "運用者指示" : "AI分析";
          return `- [${src}/${r.priority}] ${r.content}`;
        })
        .join("\n");
    }
  } catch { /* ignore */ }

  // 3. Pipeline status
  let pipelineStatus = "";
  try {
    const statusRows = await getAllRows("pipeline_status");
    if (statusRows.length > 0) {
      pipelineStatus = statusRows
        .map((r) => `- ${r.script_name}: ${r.status} (${r.detail || ""}) ${r.timestamp || ""}`)
        .join("\n");
    }
  } catch { /* ignore */ }

  return `あなたはMarketProbe事業検証自動化システムの運用アドバイザーです。
運用者からのフィードバック・指示を受け取り、システム改善に活かします。

## あなたの役割
1. パフォーマンスデータに基づく分析・アドバイス提供
2. 運用者の戦略的指示を理解し、[DIRECTIVE: category] タグで分類
3. 過去の学習メモリを参照した文脈のある回答

## 指示の分類
運用者が「〜して」「〜に変更して」等の指示を出した場合、回答の末尾に以下のタグを付けてください：
[DIRECTIVE: lp_optimization] — LP改善に関する指示
[DIRECTIVE: sns_strategy] — SNS戦略に関する指示
[DIRECTIVE: form_sales] — フォーム営業に関する指示
[DIRECTIVE: idea_generation] — 事業案生成に関する指示
[DIRECTIVE: general] — その他の一般的な指示

※ 質問や分析依頼にはタグ不要です。明確な方針変更・指示の場合のみ付けてください。

${performanceSummary ? `## 直近のパフォーマンス (7日間)\n${performanceSummary}\n` : "## パフォーマンスデータ\nまだデータがありません。\n"}

${learningMemory ? `## 学習メモリ (アクティブ)\n${learningMemory}\n` : ""}

${pipelineStatus ? `## パイプライン状況\n${pipelineStatus}\n` : ""}

日本語で回答してください。データに基づく具体的なアドバイスを心がけてください。`;
}

async function saveDirective(content: string, category: string): Promise<void> {
  try {
    await ensureSheetExists("learning_memory", [
      "id", "type", "source", "category", "content",
      "context_json", "confidence", "priority", "status",
      "applied_count", "created_at", "expires_at",
    ]);

    const now = new Date().toISOString().replace("T", " ").substring(0, 16);
    const id = generateId();

    await appendRows("learning_memory", [[
      id, "directive", "human_chat", category,
      content, "{}", "1.0", "high",
      "active", "0", now, "",
    ]]);
  } catch (err) {
    console.error("Failed to save directive:", err);
  }
}

function extractDirective(text: string): { category: string; content: string } | null {
  const match = text.match(/\[DIRECTIVE:\s*([\w_]+)\]/);
  if (!match) return null;

  const category = match[1];
  // Extract the directive content (text before the tag, stripped of decorative text)
  const beforeTag = text.substring(0, text.indexOf("[DIRECTIVE:")).trim();
  // Take the last meaningful sentence/paragraph as the directive
  const lines = beforeTag.split("\n").filter((l) => l.trim());
  const content = lines.length > 0 ? lines[lines.length - 1].trim() : beforeTag;

  return { category, content };
}

// ---------------------------------------------------------------------------
// POST /api/feedback/chat
// ---------------------------------------------------------------------------

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { message } = body as { message: string };

    if (!message) {
      return new Response(
        JSON.stringify({ error: "message is required" }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      );
    }

    const systemPrompt = await buildSystemPrompt();
    const claudeKey = process.env.CLAUDE_API_KEY || process.env.ANTHROPIC_API_KEY || "";
    const geminiKey = process.env.GEMINI_API_KEY || "";
    const encoder = new TextEncoder();

    // Try Gemini first, fall back to Claude
    if (geminiKey) {
      try {
        const readable = await createGeminiStream(geminiKey, systemPrompt, message, encoder);
        return new Response(readable, {
          headers: {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            Connection: "keep-alive",
          },
        });
      } catch (err) {
        console.warn("Gemini streaming failed, falling back to Claude:", err);
        if (!claudeKey) throw err;
      }
    }

    if (claudeKey) {
      const readable = await createClaudeStream(claudeKey, systemPrompt, message, encoder);
      return new Response(readable, {
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
        },
      });
    }

    return new Response(
      JSON.stringify({ error: "No AI API key configured" }),
      { status: 500, headers: { "Content-Type": "application/json" } },
    );
  } catch (err) {
    console.error("Feedback chat error:", err);
    return new Response(
      JSON.stringify({ error: "Internal error" }),
      { status: 500, headers: { "Content-Type": "application/json" } },
    );
  }
}

// ---------------------------------------------------------------------------
// Claude streaming
// ---------------------------------------------------------------------------

async function createClaudeStream(
  apiKey: string,
  systemPrompt: string,
  message: string,
  encoder: TextEncoder,
): Promise<ReadableStream> {
  const anthropic = new Anthropic({ apiKey });

  const stream = anthropic.messages.stream({
    model: "claude-sonnet-4-5-20250929",
    max_tokens: 4096,
    system: systemPrompt,
    messages: [{ role: "user", content: message }],
  });

  let fullText = "";

  return new ReadableStream({
    async start(controller) {
      try {
        for await (const event of stream) {
          if (event.type === "content_block_delta" && event.delta.type === "text_delta") {
            fullText += event.delta.text;
            const data = JSON.stringify({ text: event.delta.text });
            controller.enqueue(encoder.encode(`data: ${data}\n\n`));
          }
        }

        // Check for directives and save
        const directive = extractDirective(fullText);
        if (directive) {
          await saveDirective(directive.content, directive.category);
          const meta = JSON.stringify({
            directive_saved: true,
            category: directive.category,
          });
          controller.enqueue(encoder.encode(`data: ${meta}\n\n`));
        }

        controller.enqueue(encoder.encode("data: [DONE]\n\n"));
        controller.close();
      } catch (err) {
        console.error("Claude stream error:", err);
        controller.error(err);
      }
    },
  });
}

// ---------------------------------------------------------------------------
// Gemini streaming
// ---------------------------------------------------------------------------

async function createGeminiStream(
  apiKey: string,
  systemPrompt: string,
  message: string,
  encoder: TextEncoder,
): Promise<ReadableStream> {
  const geminiModel = process.env.GEMINI_MODEL || "gemini-2.5-flash";
  const genAI = new GoogleGenerativeAI(apiKey);
  const model = genAI.getGenerativeModel({
    model: geminiModel,
    systemInstruction: systemPrompt,
  });

  const result = await model.generateContentStream(message);
  let fullText = "";

  return new ReadableStream({
    async start(controller) {
      try {
        for await (const chunk of result.stream) {
          const text = chunk.text();
          if (text) {
            fullText += text;
            const data = JSON.stringify({ text });
            controller.enqueue(encoder.encode(`data: ${data}\n\n`));
          }
        }

        // Check for directives and save
        const directive = extractDirective(fullText);
        if (directive) {
          await saveDirective(directive.content, directive.category);
          const meta = JSON.stringify({
            directive_saved: true,
            category: directive.category,
          });
          controller.enqueue(encoder.encode(`data: ${meta}\n\n`));
        }

        controller.enqueue(encoder.encode("data: [DONE]\n\n"));
        controller.close();
      } catch (err) {
        console.error("Gemini stream error:", err);
        controller.error(err);
      }
    },
  });
}
