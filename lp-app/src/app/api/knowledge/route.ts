import { NextRequest, NextResponse } from "next/server";
import { getAllRows, appendRows, ensureSheetExists } from "@/lib/sheets";
import { getAccessToken, GCP_PROJECT } from "@/lib/gcp-auth";
import Anthropic from "@anthropic-ai/sdk";
import { GoogleGenerativeAI } from "@google/generative-ai";

// Allow large PDF uploads (up to 100MB)
export const maxDuration = 120;

const GCS_BUCKET = process.env.GCS_BUCKET_NAME || "marketprobe-automation-lps";

const KNOWLEDGE_HEADERS = [
  "id", "filename", "gcs_path", "title", "summary", "chapters_json", "uploaded_at",
];

/**
 * GET /api/knowledge
 * Returns all registered knowledge base entries.
 */
export async function GET() {
  try {
    await ensureSheetExists("knowledge_base", KNOWLEDGE_HEADERS);
    const rows = await getAllRows("knowledge_base");

    const documents = rows.map((row) => {
      let chapters: unknown[] = [];
      let keyFrameworks: string[] = [];
      let applicableTo = "";

      if (row.chapters_json) {
        try {
          const parsed = JSON.parse(row.chapters_json);
          chapters = parsed.chapters || [];
          keyFrameworks = parsed.key_frameworks || [];
          applicableTo = parsed.applicable_to || "";
        } catch { /* ignore */ }
      }

      return {
        id: row.id || "",
        filename: row.filename || "",
        title: row.title || "",
        summary: row.summary || "",
        chapterCount: chapters.length,
        keyFrameworks,
        applicableTo,
        uploadedAt: row.uploaded_at || "",
      };
    });

    return NextResponse.json({ documents });
  } catch (err) {
    console.error("Knowledge GET error:", err);
    return NextResponse.json({ documents: [] });
  }
}

// ---------------------------------------------------------------------------
// AI extraction helpers
// ---------------------------------------------------------------------------

const EXTRACTION_PROMPT = `この書籍/ドキュメントを分析し、以下のJSON形式で出力してください。
JSON以外のテキストは含めないでください。

\`\`\`json
{
  "title": "書籍タイトル",
  "summary": "全体の要約（300-500文字。主要なフレームワーク、方法論、重要な概念を含める）",
  "chapters": [
    {
      "number": 1,
      "title": "章タイトル",
      "summary": "章の要約（100-200文字）"
    }
  ],
  "key_frameworks": ["フレームワーク名1", "フレームワーク名2"],
  "applicable_to": "この書籍の知識が特に有用な事業フェーズや活動（50-100文字）"
}
\`\`\``;

async function extractWithClaude(pdfBase64: string): Promise<string> {
  const anthropicKey = process.env.CLAUDE_API_KEY || process.env.ANTHROPIC_API_KEY || "";
  const anthropic = new Anthropic({ apiKey: anthropicKey });

  const response = await anthropic.messages.create({
    model: "claude-sonnet-4-5-20250929",
    max_tokens: 8192,
    messages: [
      {
        role: "user",
        content: [
          {
            type: "document",
            source: {
              type: "base64",
              media_type: "application/pdf",
              data: pdfBase64,
            },
          },
          {
            type: "text",
            text: EXTRACTION_PROMPT,
          },
        ],
      },
    ],
  });

  for (const block of response.content) {
    if (block.type === "text") return block.text;
  }
  return "";
}

async function extractWithGemini(pdfBase64: string): Promise<string> {
  const geminiKey = process.env.GEMINI_API_KEY || "";
  const geminiModel = process.env.GEMINI_MODEL || "gemini-2.5-flash";
  const genAI = new GoogleGenerativeAI(geminiKey);
  const model = genAI.getGenerativeModel({ model: geminiModel });

  const result = await model.generateContent([
    {
      inlineData: {
        mimeType: "application/pdf",
        data: pdfBase64,
      },
    },
    { text: EXTRACTION_PROMPT },
  ]);

  return result.response.text();
}

/**
 * POST /api/knowledge
 * Upload a PDF and index it.
 * Expects multipart/form-data with:
 *   - file: PDF file
 *   - title: optional title override
 */
export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const file = formData.get("file") as File | null;
    const title = formData.get("title") as string | null;

    if (!file || !file.name.endsWith(".pdf")) {
      return NextResponse.json(
        { error: "PDF file is required" },
        { status: 400 },
      );
    }

    const filename = file.name;
    const docId = filename.replace(/\.pdf$/i, "");

    // Check if already exists
    await ensureSheetExists("knowledge_base", KNOWLEDGE_HEADERS);
    const existing = await getAllRows("knowledge_base");
    if (existing.some((r) => r.id === docId)) {
      return NextResponse.json(
        { error: "Document already registered", id: docId },
        { status: 409 },
      );
    }

    // 1. Upload to GCS
    const gcsPath = `knowledge/${filename}`;
    const fileBuffer = Buffer.from(await file.arrayBuffer());

    const token = await getAccessToken();
    const uploadUrl = `https://storage.googleapis.com/upload/storage/v1/b/${GCS_BUCKET}/o?uploadType=media&name=${encodeURIComponent(gcsPath)}`;

    const uploadRes = await fetch(uploadUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/pdf",
      },
      body: fileBuffer,
    });

    if (!uploadRes.ok) {
      const errText = await uploadRes.text();
      console.error("GCS upload error:", errText);
      return NextResponse.json(
        { error: "Failed to upload to GCS" },
        { status: 500 },
      );
    }

    // 2. Extract knowledge via AI (Gemini primary → Claude fallback)
    const pdfBase64 = fileBuffer.toString("base64");
    let rawText = "";

    const claudeKey = process.env.CLAUDE_API_KEY || process.env.ANTHROPIC_API_KEY || "";
    const geminiKey = process.env.GEMINI_API_KEY || "";

    if (geminiKey) {
      try {
        rawText = await extractWithGemini(pdfBase64);
      } catch (err) {
        console.warn("Gemini API failed, falling back to Claude:", err);
        if (claudeKey) {
          rawText = await extractWithClaude(pdfBase64);
        } else {
          throw err;
        }
      }
    } else if (claudeKey) {
      console.info("No Gemini API key, using Claude for extraction");
      rawText = await extractWithClaude(pdfBase64);
    } else {
      return NextResponse.json(
        { error: "No AI API key configured (GEMINI_API_KEY or CLAUDE_API_KEY)" },
        { status: 500 },
      );
    }

    // Parse AI response
    let cleaned = rawText.trim();
    if (cleaned.startsWith("```")) {
      const firstNewline = cleaned.indexOf("\n");
      const lastFence = cleaned.lastIndexOf("```");
      cleaned = cleaned.substring(firstNewline + 1, lastFence).trim();
    }

    const knowledge = JSON.parse(cleaned);
    const docTitle = title || knowledge.title || filename;
    const summary = knowledge.summary || "";
    const chaptersJson = JSON.stringify(knowledge, null, 0);

    // 3. Save to knowledge_base sheet
    const now = new Date().toISOString().replace("T", " ").substring(0, 16);
    await appendRows("knowledge_base", [[
      docId,
      filename,
      gcsPath,
      docTitle,
      summary,
      chaptersJson,
      now,
    ]]);

    return NextResponse.json({
      ok: true,
      id: docId,
      title: docTitle,
      summary,
      chapterCount: knowledge.chapters?.length || 0,
      keyFrameworks: knowledge.key_frameworks || [],
    });
  } catch (err) {
    console.error("Knowledge POST error:", err);
    return NextResponse.json(
      { error: "Internal error" },
      { status: 500 },
    );
  }
}
