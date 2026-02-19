import { NextRequest } from "next/server";
import { getAllRows, ensureSheetExists } from "@/lib/sheets";
import Anthropic from "@anthropic-ai/sdk";
import { GoogleGenerativeAI } from "@google/generative-ai";

const SYSTEM_PROMPT_PREFIX = `あなたは事業計画・事業検証の専門アドバイザーです。
以下の書籍・ドキュメントの知識を活用して、ユーザーの質問に日本語で回答してください。
回答では具体的なフレームワークや手法を参照し、実践的なアドバイスを提供してください。

## 知識ベース
`;

/**
 * POST /api/knowledge/chat
 * Body: { message: string, knowledgeIds?: string[] }
 *
 * Streams a response from AI (Claude → Gemini fallback) based on knowledge base content.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { message, knowledgeIds } = body as {
      message: string;
      knowledgeIds?: string[];
    };

    if (!message) {
      return new Response(
        JSON.stringify({ error: "message is required" }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      );
    }

    // Load knowledge base summaries
    await ensureSheetExists("knowledge_base", [
      "id", "filename", "gcs_path", "title", "summary", "chapters_json", "uploaded_at",
    ]);
    const rows = await getAllRows("knowledge_base");

    // Filter by knowledgeIds if specified
    const filtered = knowledgeIds && knowledgeIds.length > 0
      ? rows.filter((r) => knowledgeIds.includes(r.id))
      : rows;

    // Build knowledge context
    let knowledgeContext = "";
    for (const row of filtered) {
      const title = row.title || row.filename || "";
      const summary = row.summary || "";
      let chaptersDetail = "";

      if (row.chapters_json) {
        try {
          const parsed = JSON.parse(row.chapters_json);
          const chapters = parsed.chapters || [];
          const frameworks = parsed.key_frameworks || [];

          if (chapters.length > 0) {
            chaptersDetail = "\n章構成:\n" + chapters
              .map((c: { number: number; title: string; summary: string }) =>
                `  ${c.number}. ${c.title}: ${c.summary}`
              )
              .join("\n");
          }
          if (frameworks.length > 0) {
            chaptersDetail += `\n主要フレームワーク: ${frameworks.join(", ")}`;
          }
        } catch { /* ignore */ }
      }

      knowledgeContext += `\n### ${title}\n${summary}${chaptersDetail}\n`;
    }

    const systemPrompt = SYSTEM_PROMPT_PREFIX + (knowledgeContext || "（知識ベースはまだ登録されていません）");

    const claudeKey = process.env.CLAUDE_API_KEY || process.env.ANTHROPIC_API_KEY || "";
    const geminiKey = process.env.GEMINI_API_KEY || "";

    // Try Gemini streaming first, fall back to Claude
    const encoder = new TextEncoder();

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
    console.error("Knowledge chat error:", err);
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

  return new ReadableStream({
    async start(controller) {
      try {
        for await (const event of stream) {
          if (event.type === "content_block_delta" && event.delta.type === "text_delta") {
            const data = JSON.stringify({ text: event.delta.text });
            controller.enqueue(encoder.encode(`data: ${data}\n\n`));
          }
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

  return new ReadableStream({
    async start(controller) {
      try {
        for await (const chunk of result.stream) {
          const text = chunk.text();
          if (text) {
            const data = JSON.stringify({ text });
            controller.enqueue(encoder.encode(`data: ${data}\n\n`));
          }
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
