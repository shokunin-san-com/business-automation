import { NextRequest, NextResponse } from "next/server";
import { getAccessToken, GCP_PROJECT, GCP_REGION, JOB_MAP } from "@/lib/gcp-auth";

// All scheduler job names
const ALL_SCHEDULERS = Object.values(JOB_MAP).flatMap((j) => j.schedulers);

/**
 * GET /api/dashboard/scheduler
 * Returns the state (ENABLED/PAUSED) of all Cloud Scheduler jobs.
 */
export async function GET() {
  try {
    const token = await getAccessToken();
    const url = `https://cloudscheduler.googleapis.com/v1/projects/${GCP_PROJECT}/locations/${GCP_REGION}/jobs`;

    const res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (!res.ok) {
      const errText = await res.text();
      console.error("Scheduler list error:", res.status, errText);
      return NextResponse.json({ schedulers: {} });
    }

    const data = await res.json();
    const jobs = data.jobs || [];

    // Build map: scheduler name -> state
    const schedulers: Record<string, { state: string; schedule: string; nextRun: string }> = {};

    for (const job of jobs) {
      // job.name format: "projects/.../locations/.../jobs/schedule-idea-generator"
      const shortName = job.name?.split("/").pop() || "";
      if (ALL_SCHEDULERS.includes(shortName)) {
        schedulers[shortName] = {
          state: job.state || "ENABLED",
          schedule: job.schedule || "",
          nextRun: job.scheduleTime || "",
        };
      }
    }

    return NextResponse.json({ schedulers });
  } catch (err) {
    console.error("Scheduler GET error:", err);
    return NextResponse.json({ schedulers: {} });
  }
}

/**
 * PATCH /api/dashboard/scheduler
 * Body: { jobId: "schedule-idea-generator", schedule: "0 9 * * *", timeZone?: "Asia/Tokyo" }
 * Updates the cron schedule for a Cloud Scheduler job.
 */
export async function PATCH(request: NextRequest) {
  try {
    const body = await request.json();
    const { jobId, schedule, timeZone = "Asia/Tokyo" } = body as {
      jobId: string;
      schedule: string;
      timeZone?: string;
    };

    if (!jobId || !schedule) {
      return NextResponse.json({ error: "jobId and schedule are required" }, { status: 400 });
    }

    // Basic cron validation: must have exactly 5 fields
    const cronFields = schedule.trim().split(/\s+/);
    if (cronFields.length !== 5) {
      return NextResponse.json(
        { error: "Invalid cron format. Expected 5 fields: minute hour day month weekday" },
        { status: 400 },
      );
    }

    // Ensure the scheduler name is valid
    if (!ALL_SCHEDULERS.includes(jobId)) {
      return NextResponse.json({ error: "Unknown scheduler job" }, { status: 400 });
    }

    const token = await getAccessToken();
    const jobPath = `projects/${GCP_PROJECT}/locations/${GCP_REGION}/jobs/${jobId}`;
    const url = `https://cloudscheduler.googleapis.com/v1/${jobPath}?updateMask=schedule,timeZone`;

    const res = await fetch(url, {
      method: "PATCH",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        schedule,
        timeZone,
      }),
    });

    if (!res.ok) {
      const errText = await res.text();
      console.error("Scheduler PATCH error:", res.status, errText);
      return NextResponse.json({ error: "Failed to update schedule", detail: errText }, { status: res.status });
    }

    const updated = await res.json();
    return NextResponse.json({
      ok: true,
      schedule: updated.schedule,
      timeZone: updated.timeZone,
    });
  } catch (err) {
    console.error("Scheduler PATCH error:", err);
    return NextResponse.json({ error: "Internal error" }, { status: 500 });
  }
}

/**
 * POST /api/dashboard/scheduler
 * Body: { scheduler: "schedule-idea-generator", action: "pause" | "resume" }
 *   OR  { action: "pause_all" | "resume_all" }
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { scheduler, action } = body as {
      scheduler?: string;
      action: "pause" | "resume" | "pause_all" | "resume_all";
    };

    const token = await getAccessToken();
    const basePath = `https://cloudscheduler.googleapis.com/v1/projects/${GCP_PROJECT}/locations/${GCP_REGION}/jobs`;

    // Determine which schedulers to act on
    let targets: string[];
    let apiAction: "pause" | "resume";

    if (action === "pause_all") {
      targets = ALL_SCHEDULERS;
      apiAction = "pause";
    } else if (action === "resume_all") {
      targets = ALL_SCHEDULERS;
      apiAction = "resume";
    } else if (scheduler && (action === "pause" || action === "resume")) {
      targets = [scheduler];
      apiAction = action;
    } else {
      return NextResponse.json({ error: "Invalid request" }, { status: 400 });
    }

    const results: Record<string, boolean> = {};

    for (const name of targets) {
      try {
        const url = `${basePath}/${name}:${apiAction}`;
        const res = await fetch(url, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
        });
        results[name] = res.ok;
      } catch {
        results[name] = false;
      }
    }

    return NextResponse.json({ ok: true, results });
  } catch (err) {
    console.error("Scheduler POST error:", err);
    return NextResponse.json({ error: "Internal error" }, { status: 500 });
  }
}
