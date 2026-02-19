import { NextRequest, NextResponse } from "next/server";
import { getAccessToken, GCP_PROJECT, GCP_REGION, JOB_MAP } from "@/lib/gcp-auth";
import { appendRows, ensureSheetExists } from "@/lib/sheets";

/**
 * POST /api/dashboard/execute
 * Body: { scriptId: "0_idea_generator" }
 *
 * Triggers a Cloud Run Job manually and logs execution to Sheets.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { scriptId } = body as { scriptId: string };

    if (!scriptId || !JOB_MAP[scriptId]) {
      return NextResponse.json(
        { error: `Unknown script: ${scriptId}` },
        { status: 400 },
      );
    }

    const { jobId } = JOB_MAP[scriptId];

    // Call Cloud Run Jobs API to execute the job
    const token = await getAccessToken();
    const url = `https://${GCP_REGION}-run.googleapis.com/v2/projects/${GCP_PROJECT}/locations/${GCP_REGION}/jobs/${jobId}:run`;

    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
    });

    if (!res.ok) {
      const errText = await res.text();
      console.error("Cloud Run execute error:", errText);
      return NextResponse.json(
        { error: "Failed to execute job", detail: errText },
        { status: res.status },
      );
    }

    const result = await res.json();
    const executionName = result.metadata?.name || result.name || "";

    // Log execution to Sheets
    try {
      await ensureSheetExists("execution_logs", [
        "timestamp", "job_name", "trigger", "status", "detail", "executed_by",
      ]);
      await appendRows("execution_logs", [[
        new Date().toISOString(),
        scriptId,
        "manual",
        "triggered",
        `Execution: ${executionName}`,
        "dashboard",
      ]]);
    } catch {
      /* logging is best-effort */
    }

    return NextResponse.json({
      ok: true,
      jobId,
      executionName,
    });
  } catch (err) {
    console.error("Execute error:", err);
    return NextResponse.json(
      { error: "Internal error" },
      { status: 500 },
    );
  }
}
