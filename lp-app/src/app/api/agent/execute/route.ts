import { NextRequest, NextResponse } from "next/server";
import { getAccessToken, GCP_PROJECT, GCP_REGION } from "@/lib/gcp-auth";
import { appendRows, ensureSheetExists } from "@/lib/sheets";

/**
 * POST /api/agent/execute
 *
 * The "bridge" between chat interfaces (Google Chat / Slack) and the
 * autonomous agent (agent/orchestrator.py running on Cloud Run Jobs).
 *
 * Body: { task: string, context?: { triggered_by, source, thread_id? } }
 *
 * Triggers the `agent-orchestrator` Cloud Run Job with AGENT_TASK and
 * AGENT_CONTEXT as container-override environment variables.
 * Returns 200 immediately — results are delivered asynchronously via
 * Google Chat / Slack webhook notifications from the agent.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { task, context } = body as {
      task: string;
      context?: {
        triggered_by?: string;
        source?: string;
        thread_id?: string;
      };
    };

    if (!task || typeof task !== "string") {
      return NextResponse.json(
        { error: "task is required and must be a string" },
        { status: 400 },
      );
    }

    // Agent orchestrator Cloud Run Job
    const jobId = "agent-orchestrator";

    const token = await getAccessToken();
    const url = `https://${GCP_REGION}-run.googleapis.com/v2/projects/${GCP_PROJECT}/locations/${GCP_REGION}/jobs/${jobId}:run`;

    // Build container override with AGENT_TASK and AGENT_CONTEXT env vars
    const envOverrides: { name: string; value: string }[] = [
      { name: "AGENT_TASK", value: task },
    ];
    if (context) {
      envOverrides.push({
        name: "AGENT_CONTEXT",
        value: JSON.stringify(context),
      });
    }

    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        overrides: {
          containerOverrides: [
            {
              env: envOverrides,
            },
          ],
        },
      }),
    });

    if (!res.ok) {
      const errText = await res.text();
      console.error("[agent/execute] Cloud Run execute error:", errText);
      return NextResponse.json(
        { error: "Failed to execute agent", detail: errText },
        { status: res.status },
      );
    }

    const result = await res.json();
    const executionName =
      result.metadata?.name || result.name || "";

    // Log execution (best-effort)
    try {
      await ensureSheetExists("execution_logs", [
        "timestamp",
        "job_name",
        "trigger",
        "status",
        "detail",
        "executed_by",
      ]);
      await appendRows("execution_logs", [
        [
          new Date().toISOString(),
          "agent-orchestrator",
          "chat-bridge",
          "triggered",
          `Task: ${task.substring(0, 100)} | Execution: ${executionName}`,
          context?.triggered_by || "unknown",
        ],
      ]);
    } catch {
      /* logging is best-effort */
    }

    return NextResponse.json({
      ok: true,
      jobId,
      executionName,
      message:
        "Agent task submitted. Results will be delivered via notification.",
    });
  } catch (err) {
    console.error("[agent/execute] Error:", err);
    return NextResponse.json(
      { error: "Internal error" },
      { status: 500 },
    );
  }
}
