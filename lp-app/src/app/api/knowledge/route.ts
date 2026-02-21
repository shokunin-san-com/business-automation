import { NextRequest, NextResponse } from "next/server";
import { getAllRows, appendRows, ensureSheetExists } from "@/lib/sheets";
import { getAccessToken } from "@/lib/gcp-auth";
import Anthropic from "@anthropic-ai/sdk";
import { GoogleGenerativeAI } from "@google/generative-ai";

// Allow large uploads (up to 100MB)
export const maxDuration = 120;

const GCS_BUCKET = process.env.GCS_BUCKET_NAME || "marketprobe-automation-lps";

const KNOWLEDGE_HEADERS = [
  "id", "filename", "gcs_path", "title", "summary", "chapters_json", "uploaded_at",
];

// ---------------------------------------------------------------------------
// Supported file types
// ---------------------------------------------------------------------------
type FileCategory = "document" | "image" | "text";

const SUPPORTED_EXTENSIONS: Record<string, { mimeType: string; category: FileCategory }> = {
  ".pdf":  { mimeType: "application/pdf", category: "document" },
  ".csv":  { mimeType: "text/csv", category: "text" },
  ".xlsx": { mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", category: "text" },
  ".xls":  { mimeType: "application/vnd.ms-excel", category: "text" },
  ".png":  { mimeType: "image/png", category: "image" },
  ".jpg":  { mimeType: "image/jpeg", category: "image" },
  ".jpeg": { mimeType: "image/jpeg", category: "image" },
  ".webp": { mimeType: "image/webp", category: "image" },
};

function getFileInfo(filename: string) {
  const ext = filename.substring(filename.lastIndexOf(".")).toLowerCase();
  return { info: SUPPORTED_EXTENSIONS[ext] || null, ext };
}

// ---------------------------------------------------------------------------
// Text extraction helpers (CSV / Excel)
// ---------------------------------------------------------------------------
function extractTextFromCSV(buffer: Buffer): string {
  return buffer.toString("utf-8");
}

async function extractTextFromExcel(buffer: Buffer): Promise<string> {
  const XLSX = await import("xlsx");
  const workbook = XLSX.read(buffer, { type: "buffer" });
  const lines: string[] = [];
  for (const sheetName of workbook.SheetNames) {
    const sheet = workbook.Sheets[sheetName];
    const csv = XLSX.utils.sheet_to_csv(sheet);
    lines.push(`=== Sheet: ${sheetName} ===`);
    lines.push(csv);
  }
  return lines.join("\n\n");
}

// ---------------------------------------------------------------------------
// Extraction prompts per file type
// ---------------------------------------------------------------------------
const DOC_EXTRACTION_PROMPT = `この書籍/ドキュメントを分析し、以下のJSON形式で出力してください。
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

function getExtractionPrompt(category: FileCategory, filename: string): string {
  if (category === "image") {
    return `この画像/図表を分析し、以下のJSON形式で出力してください。
JSON以外のテキストは含めないでください。

\`\`\`json
{
  "title": "画像の内容を表すタイトル",
  "summary": "画像の内容の要約（100-300文字。図表の場合はデータの意味・傾向を含める）",
  "chapters": [
    {"number": 1, "title": "主要な情報", "summary": "画像から読み取れる主要な情報"}
  ],
  "key_frameworks": [],
  "applicable_to": "この画像の情報が有用な場面（30-50文字）"
}
\`\`\``;
  }

  if (category === "text") {
    return `このデータ（${filename}）を分析し、以下のJSON形式で出力してください。
JSON以外のテキストは含めないでください。

\`\`\`json
{
  "title": "データの内容を表すタイトル",
  "summary": "データの要約（200-400文字。主要な列・指標・傾向を含める）",
  "chapters": [
    {"number": 1, "title": "データ概要", "summary": "データの構造と主要な特徴"}
  ],
  "key_frameworks": [],
  "applicable_to": "このデータが有用な事業フェーズや活動（30-50文字）"
}
\`\`\``;
  }

  return DOC_EXTRACTION_PROMPT;
}

// ---------------------------------------------------------------------------
// AI extraction helpers
// ---------------------------------------------------------------------------
async function extractWithClaude(
  base64Data: string,
  mimeType: string,
  category: FileCategory,
  prompt: string,
): Promise<string> {
  const anthropicKey = process.env.CLAUDE_API_KEY || process.env.ANTHROPIC_API_KEY || "";
  const anthropic = new Anthropic({ apiKey: anthropicKey });

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const contentBlocks: any[] = [];

  if (category === "document") {
    contentBlocks.push({
      type: "document",
      source: { type: "base64", media_type: mimeType, data: base64Data },
    });
  } else if (category === "image") {
    contentBlocks.push({
      type: "image",
      source: { type: "base64", media_type: mimeType, data: base64Data },
    });
  } else {
    // Text content (CSV/Excel already converted)
    const textContent = Buffer.from(base64Data, "base64").toString("utf-8");
    contentBlocks.push({
      type: "text",
      text: `以下はアップロードされたデータの内容です:\n\n${textContent}`,
    });
  }

  contentBlocks.push({ type: "text", text: prompt });

  const response = await anthropic.messages.create({
    model: "claude-sonnet-4-5-20250929",
    max_tokens: 8192,
    messages: [{ role: "user", content: contentBlocks }],
  });

  for (const block of response.content) {
    if (block.type === "text") return block.text;
  }
  return "";
}

async function extractWithGemini(
  base64Data: string,
  mimeType: string,
  category: FileCategory,
  prompt: string,
): Promise<string> {
  const geminiKey = process.env.GEMINI_API_KEY || "";
  const geminiModel = process.env.GEMINI_MODEL || "gemini-2.5-flash";
  const genAI = new GoogleGenerativeAI(geminiKey);
  const model = genAI.getGenerativeModel({ model: geminiModel });

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const parts: any[] = [];

  if (category === "text") {
    const textContent = Buffer.from(base64Data, "base64").toString("utf-8");
    parts.push({ text: `以下はアップロードされたデータの内容です:\n\n${textContent}` });
  } else {
    parts.push({ inlineData: { mimeType, data: base64Data } });
  }

  parts.push({ text: prompt });
  const result = await model.generateContent(parts);
  return result.response.text();
}

// ---------------------------------------------------------------------------
// GET /api/knowledge
// ---------------------------------------------------------------------------
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
// POST /api/knowledge
// Upload a file (PDF, CSV, Excel, Image) and index it.
// ---------------------------------------------------------------------------
export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const file = formData.get("file") as File | null;
    const title = formData.get("title") as string | null;

    if (!file) {
      return NextResponse.json({ error: "File is required" }, { status: 400 });
    }

    const { info: fileInfo, ext } = getFileInfo(file.name);
    if (!fileInfo) {
      const supported = Object.keys(SUPPORTED_EXTENSIONS).join(", ");
      return NextResponse.json(
        { error: `未対応のファイル形式です。対応形式: ${supported}` },
        { status: 400 },
      );
    }

    const filename = file.name;
    const docId = filename.substring(0, filename.lastIndexOf("."));

    // Check if already exists
    await ensureSheetExists("knowledge_base", KNOWLEDGE_HEADERS);
    const existing = await getAllRows("knowledge_base");
    if (existing.some((r) => r.id === docId)) {
      return NextResponse.json(
        { error: "同名のドキュメントが既に登録されています", id: docId },
        { status: 409 },
      );
    }

    // 1. Upload to GCS (non-blocking — skip if fails)
    const gcsPath = `knowledge/${filename}`;
    const fileBuffer = Buffer.from(await file.arrayBuffer());

    let gcsUploaded = false;
    try {
      const token = await getAccessToken();
      const uploadUrl = `https://storage.googleapis.com/upload/storage/v1/b/${GCS_BUCKET}/o?uploadType=media&name=${encodeURIComponent(gcsPath)}`;

      const uploadRes = await fetch(uploadUrl, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": fileInfo.mimeType,
        },
        body: fileBuffer,
      });

      if (uploadRes.ok) {
        gcsUploaded = true;
      } else {
        const errText = await uploadRes.text();
        console.warn("GCS upload failed (continuing without storage):", errText);
      }
    } catch (gcsErr) {
      console.warn("GCS upload error (continuing without storage):", gcsErr);
    }

    // 2. Prepare data for AI extraction
    let dataForAI: string;

    if (ext === ".xlsx" || ext === ".xls") {
      const textContent = await extractTextFromExcel(fileBuffer);
      dataForAI = Buffer.from(textContent).toString("base64");
    } else if (ext === ".csv") {
      const textContent = extractTextFromCSV(fileBuffer);
      dataForAI = Buffer.from(textContent).toString("base64");
    } else {
      dataForAI = fileBuffer.toString("base64");
    }

    const extractionPrompt = getExtractionPrompt(fileInfo.category, filename);

    // 3. Extract knowledge via AI (Gemini primary → Claude fallback)
    let rawText = "";
    const claudeKey = process.env.CLAUDE_API_KEY || process.env.ANTHROPIC_API_KEY || "";
    const geminiKey = process.env.GEMINI_API_KEY || "";

    if (geminiKey) {
      try {
        rawText = await extractWithGemini(dataForAI, fileInfo.mimeType, fileInfo.category, extractionPrompt);
      } catch (err) {
        console.warn("Gemini API failed, falling back to Claude:", err);
        if (claudeKey) {
          rawText = await extractWithClaude(dataForAI, fileInfo.mimeType, fileInfo.category, extractionPrompt);
        } else {
          throw err;
        }
      }
    } else if (claudeKey) {
      console.info("No Gemini API key, using Claude for extraction");
      rawText = await extractWithClaude(dataForAI, fileInfo.mimeType, fileInfo.category, extractionPrompt);
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

    // 4. Save to knowledge_base sheet
    const now = new Date().toISOString().replace("T", " ").substring(0, 16);
    await appendRows("knowledge_base", [[
      docId,
      filename,
      gcsUploaded ? gcsPath : "",
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
    const errorMessage = err instanceof Error ? err.message : "Internal error";

    if (errorMessage.includes("too large") || errorMessage.includes("token") || errorMessage.includes("size") || errorMessage.includes("exceeds")) {
      return NextResponse.json(
        { error: "ファイルが大きすぎます。PDFの場合は100ページ以下を推奨します。" },
        { status: 413 },
      );
    }

    return NextResponse.json(
      { error: "Internal error" },
      { status: 500 },
    );
  }
}
