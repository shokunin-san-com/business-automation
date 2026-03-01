import { NextRequest, NextResponse } from "next/server";
import { getAllRows, appendRows, batchUpdateColumn } from "@/lib/sheets";
import { getAccessToken, GCP_PROJECT, GCP_REGION } from "@/lib/gcp-auth";

/**
 * POST /api/admin/v4-cleanup
 *
 * Performs v4 data cleanup operations:
 *   - reject_offers:  Reject all offers containing prohibited terms
 *   - unpublish_blogs: Set all blog articles to "unpublished"
 *   - all: Both operations
 *
 * Body: { action: "reject_offers" | "reject_all_offers" | "unpublish_blogs" | "all" }
 */

const PROHIBITED_TERMS = [
  "AI", "人工知能", "機械学習", "SaaS", "プラットフォーム",
  "最適化", "効率化", "ソリューション", "DX推進", "DX",
  "3D", "AR", "VR", "BIM", "CAD", "ドローン", "IoT",
  "クラウド", "アプリ", "マッチング", "サブスク",
];

function containsProhibited(offer: Record<string, string>): string[] {
  const text = [
    offer.offer_name || "",
    offer.deliverable || "",
    offer.payer || "",
  ].join(" ");

  return PROHIBITED_TERMS.filter((term) => text.includes(term));
}

/**
 * GET /api/admin/v4-cleanup
 *
 * Pipeline diagnostics: budget check, settings, recent run summary
 */
export async function GET() {
  try {
    const [costRows, settingsRows, pipelineRows, snapshots] = await Promise.all([
      getAllRows("cost_tracking").catch(() => []),
      getAllRows("settings").catch(() => []),
      getAllRows("pipeline_status").catch(() => []),
      getAllRows("settings_snapshot").catch(() => []),
    ]);

    // Monthly cost calculation (current month)
    const now = new Date();
    const monthPrefix = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
    let monthlyCostJpy = 0;
    for (const row of costRows) {
      const ts = row.timestamp || "";
      if (ts.startsWith(monthPrefix)) {
        monthlyCostJpy += parseFloat(row.cost_jpy || "0") || 0;
      }
    }

    // Budget settings
    const settingsMap = new Map(settingsRows.map((r) => [r.key, r.value]));
    const warnJpy = parseFloat(settingsMap.get("cost_warn_jpy") || "25000");
    const hardStopJpy = parseFloat(settingsMap.get("cost_hard_stop_jpy") || "30000");

    // Pipeline status
    const orchestrateStatus = pipelineRows.find((r) => r.script_name === "orchestrate_v2");

    // Recent runs (last 5)
    const recentRuns = snapshots.slice(-5).reverse().map((s) => ({
      run_id: s.run_id?.slice(0, 8),
      timestamp: s.timestamp,
    }));

    return NextResponse.json({
      budget: {
        monthly_cost_jpy: Math.round(monthlyCostJpy),
        warn_jpy: warnJpy,
        hard_stop_jpy: hardStopJpy,
        status: monthlyCostJpy >= hardStopJpy ? "HARD_STOP" : monthlyCostJpy >= warnJpy ? "WARNING" : "OK",
        month: monthPrefix,
        total_cost_rows: costRows.length,
      },
      pipeline: orchestrateStatus ? {
        status: orchestrateStatus.status,
        detail: orchestrateStatus.detail,
        timestamp: orchestrateStatus.timestamp,
        metrics_json: orchestrateStatus.metrics_json,
      } : null,
      recent_runs: recentRuns,
      key_settings: {
        ceo_profile_json: settingsMap.get("ceo_profile_json")?.slice(0, 100) || "(not set)",
        v2_continuous_mode: settingsMap.get("v2_continuous_mode") || "(not set)",
        v2_continuous_count: settingsMap.get("v2_continuous_count") || "(not set)",
        max_sv_combos: settingsMap.get("max_sv_combos") || "(not set)",
        max_competitor_combos: settingsMap.get("max_competitor_combos") || "(not set)",
      },
      cloud_run_job: await (async () => {
        try {
          const token = await getAccessToken();
          const jobUrl = `https://run.googleapis.com/v2/projects/${GCP_PROJECT}/locations/${GCP_REGION}/jobs/orchestrate-v2`;
          const res = await fetch(jobUrl, { headers: { Authorization: `Bearer ${token}` } });
          if (!res.ok) return { error: `${res.status} ${res.statusText}` };
          const job = await res.json();
          const container = job.template?.template?.containers?.[0] || {};
          return {
            image: container.image || "(unknown)",
            last_updated: job.updateTime || "",
            execution_count: job.executionCount || 0,
          };
        } catch (e) {
          return { error: String(e) };
        }
      })(),
      // Cloud Run Job recent executions
      recent_executions: await (async () => {
        try {
          const token = await getAccessToken();
          const execUrl = `https://run.googleapis.com/v2/projects/${GCP_PROJECT}/locations/${GCP_REGION}/jobs/orchestrate-v2/executions?pageSize=3`;
          const res = await fetch(execUrl, { headers: { Authorization: `Bearer ${token}` } });
          if (!res.ok) return { error: `${res.status} ${res.statusText}` };
          const data = await res.json();
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          return (data.executions || []).map((ex: any) => ({
            name: String(ex.name || "").split("/").pop(),
            status: ex.conditions?.[0]?.type || "",
            reason: ex.conditions?.[0]?.reason || "",
            message: String(ex.conditions?.[0]?.message || "").slice(0, 200),
            createTime: ex.createTime || "",
            completionTime: ex.completionTime || "",
            failedCount: ex.failedCount || 0,
            succeededCount: ex.succeededCount || 0,
          }));
        } catch (e) {
          return { error: String(e) };
        }
      })(),
      // Cloud Logging: last error logs from orchestrate-v2
      recent_logs: await (async () => {
        try {
          const token = await getAccessToken();
          const since = new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString();
          const filter = `resource.type="cloud_run_job" AND resource.labels.job_name="orchestrate-v2" AND timestamp>="${since}"`;
          const logUrl = "https://logging.googleapis.com/v2/entries:list";
          const res = await fetch(logUrl, {
            method: "POST",
            headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
            body: JSON.stringify({
              resourceNames: [`projects/${GCP_PROJECT}`],
              filter,
              orderBy: "timestamp desc",
              pageSize: 30,
            }),
          });
          if (!res.ok) {
            const errBody = await res.text();
            return { error: `${res.status}: ${errBody.slice(0, 200)}` };
          }
          const data = await res.json();
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          return (data.entries || []).map((entry: any) => ({
            timestamp: entry.timestamp || "",
            severity: entry.severity || "",
            message: String(entry.textPayload || entry.jsonPayload?.message || "").slice(0, 300),
          }));
        } catch (e) {
          return { error: String(e) };
        }
      })(),
    });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const action = body.action || "all";
    const now = new Date().toISOString().slice(0, 16).replace("T", " ");
    const report: Record<string, unknown> = {};

    // --- Task 2: Reject old offers with prohibited terms ---
    if (action === "reject_offers" || action === "all") {
      const offerRows = await getAllRows("offer_3_log");
      const ceoLog = await getAllRows("ceo_reject_log");

      // Already rejected offers
      const alreadyRejected = new Set(
        ceoLog
          .filter((r) => r.type === "offer")
          .map((r) => `${r.run_id}:${r.rejected_item}`),
      );

      const toReject: string[][] = [];
      const details: { run_id: string; offer_name: string; violations: string[] }[] = [];

      for (const offer of offerRows) {
        const rid = offer.run_id || "";
        const name = offer.offer_name || "";
        const key = `${rid}:${name}`;

        if (alreadyRejected.has(key)) continue;

        const violations = containsProhibited(offer);
        if (violations.length > 0) {
          toReject.push([
            rid,
            "offer",
            name,
            `v4自動却下: 禁止語[${violations.join(",")}]`,
            "SYSTEM",
            now,
          ]);
          details.push({ run_id: rid, offer_name: name, violations });
        }
      }

      if (toReject.length > 0) {
        await appendRows("ceo_reject_log", toReject);
      }

      report.reject_offers = {
        total_offers: offerRows.length,
        already_rejected: alreadyRejected.size,
        newly_rejected: toReject.length,
        details,
      };
    }

    // --- Reject ALL remaining offers (regardless of prohibited terms) ---
    if (action === "reject_all_offers") {
      const offerRows = await getAllRows("offer_3_log");
      const ceoLog = await getAllRows("ceo_reject_log");

      const alreadyRejected = new Set(
        ceoLog
          .filter((r) => r.type === "offer")
          .map((r) => `${r.run_id}:${r.rejected_item}`),
      );

      const toReject: string[][] = [];
      const details: { run_id: string; offer_name: string }[] = [];

      for (const offer of offerRows) {
        const rid = offer.run_id || "";
        const name = offer.offer_name || "";
        const key = `${rid}:${name}`;

        if (alreadyRejected.has(key)) continue;

        toReject.push([
          rid,
          "offer",
          name,
          "v4全却下: 旧オファー一括reject",
          "SYSTEM",
          now,
        ]);
        details.push({ run_id: rid, offer_name: name });
      }

      if (toReject.length > 0) {
        await appendRows("ceo_reject_log", toReject);
      }

      report.reject_all_offers = {
        total_offers: offerRows.length,
        already_rejected: alreadyRejected.size,
        newly_rejected: toReject.length,
        details,
      };
    }

    // --- Rebuild pipeline Docker image via Cloud Build trigger ---
    if (action === "rebuild_pipeline") {
      try {
        const token = await getAccessToken();
        // First, list existing triggers
        const triggersUrl = `https://cloudbuild.googleapis.com/v1/projects/${GCP_PROJECT}/triggers`;
        const triggersRes = await fetch(triggersUrl, { headers: { Authorization: `Bearer ${token}` } });
        if (!triggersRes.ok) {
          report.rebuild_pipeline = { error: `list triggers: ${triggersRes.status}` };
        } else {
          const triggersData = await triggersRes.json();
          const triggers = triggersData.triggers || [];
          // Find a trigger for the pipeline
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const pipelineTrigger = triggers.find((t: any) =>
            t.filename === "cloudbuild.yaml" ||
            t.name?.includes("pipeline") ||
            t.description?.includes("pipeline"),
          );
          if (pipelineTrigger) {
            // Run the existing trigger
            const runUrl = `https://cloudbuild.googleapis.com/v1/projects/${GCP_PROJECT}/triggers/${pipelineTrigger.id}:run`;
            const runRes = await fetch(runUrl, {
              method: "POST",
              headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
              body: JSON.stringify({ branchName: "main" }),
            });
            if (!runRes.ok) {
              const errText = await runRes.text();
              report.rebuild_pipeline = { error: `trigger run: ${runRes.status}: ${errText.slice(0, 300)}`, trigger_id: pipelineTrigger.id, trigger_name: pipelineTrigger.name };
            } else {
              const buildData = await runRes.json();
              const meta = buildData.metadata?.build || {};
              report.rebuild_pipeline = { build_id: meta.id || buildData.name || "", status: "TRIGGERED", trigger: pipelineTrigger.name };
            }
          } else {
            // No trigger found — try direct build as fallback
            const IMAGE = "asia-northeast1-docker.pkg.dev/marketprobe-automation/pipeline/scripts:latest";
            const buildUrl = `https://cloudbuild.googleapis.com/v1/projects/${GCP_PROJECT}/builds`;
            const buildRes = await fetch(buildUrl, {
              method: "POST",
              headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
              body: JSON.stringify({
                source: { repoSource: { projectId: GCP_PROJECT, repoName: "business-automation", branchName: "main" } },
                steps: [{ name: "gcr.io/cloud-builders/docker", args: ["build", "-t", IMAGE, "-f", "Dockerfile", "."] }],
                images: [IMAGE],
              }),
            });
            if (!buildRes.ok) {
              report.rebuild_pipeline = {
                error: `direct build: ${buildRes.status}`,
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                available_triggers: triggers.map((t: any) => ({ id: t.id, name: t.name, filename: t.filename })),
              };
            } else {
              const bd = await buildRes.json();
              report.rebuild_pipeline = { build_id: bd.metadata?.build?.id || "", status: "QUEUED" };
            }
          }
        }
      } catch (e) {
        report.rebuild_pipeline = { error: String(e) };
      }
    }

    // --- Trigger Cloud Run Job execution ---
    if (action === "run_pipeline") {
      try {
        const token = await getAccessToken();
        const jobUrl = `https://run.googleapis.com/v2/projects/${GCP_PROJECT}/locations/${GCP_REGION}/jobs/orchestrate-v2:run`;
        const runRes = await fetch(jobUrl, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        if (!runRes.ok) {
          const errText = await runRes.text();
          report.run_pipeline = { error: `${runRes.status}: ${errText.slice(0, 300)}` };
        } else {
          const runData = await runRes.json();
          report.run_pipeline = {
            execution: runData.metadata?.name || runData.name || "",
            status: "TRIGGERED",
          };
        }
      } catch (e) {
        report.run_pipeline = { error: String(e) };
      }
    }

    // --- Test Gemini API directly ---
    if (action === "test_gemini") {
      try {
        // Read GEMINI_API_KEY from Cloud Run Job env vars
        const token = await getAccessToken();
        const jobUrl = `https://run.googleapis.com/v2/projects/${GCP_PROJECT}/locations/${GCP_REGION}/jobs/orchestrate-v2`;
        const jobRes = await fetch(jobUrl, { headers: { Authorization: `Bearer ${token}` } });
        if (!jobRes.ok) {
          report.test_gemini = { error: `Can't read job: ${jobRes.status}` };
        } else {
          const job = await jobRes.json();
          const envVars = job.template?.template?.containers?.[0]?.env || [];
          const apiKeyEntry = envVars.find((e: { name: string }) => e.name === "GEMINI_API_KEY");
          const modelEntry = envVars.find((e: { name: string }) => e.name === "GEMINI_MODEL");

          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          let apiKey = (apiKeyEntry as any)?.value || "";
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const secretRef = (apiKeyEntry as any)?.valueSource?.secretKeyRef;
          if (!apiKey && secretRef) {
            try {
              const secretUrl = `https://secretmanager.googleapis.com/v1/projects/${GCP_PROJECT}/secrets/${secretRef.secret}/versions/${secretRef.version || "latest"}:access`;
              const secretRes = await fetch(secretUrl, { headers: { Authorization: `Bearer ${token}` } });
              if (secretRes.ok) {
                const secretData = await secretRes.json();
                apiKey = Buffer.from(secretData.payload?.data || "", "base64").toString("utf-8");
              } else {
                report.test_gemini = { error: `Secret Manager ${secretRes.status}`, secret: secretRef.secret };
              }
            } catch (e) {
              report.test_gemini = { error: `Secret read failed: ${String(e)}` };
            }
          }
          if (!apiKey && !report.test_gemini) {
            report.test_gemini = { error: "GEMINI_API_KEY not readable", env_structure: JSON.stringify(apiKeyEntry).slice(0, 300), env_names: envVars.map((e: { name: string }) => e.name) };
          }
          if (apiKey) {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const model = (modelEntry as any)?.value || "gemini-2.5-flash";
            // Call Gemini API with a simple test prompt
            const geminiUrl = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;
            const testRes = await fetch(geminiUrl, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                contents: [{ parts: [{ text: "JSONで回答してください: {\"test\": true, \"model\": \"あなたのモデル名\"}" }] }],
                generationConfig: { responseMimeType: "application/json", maxOutputTokens: 256, temperature: 0.1 },
              }),
            });
            if (!testRes.ok) {
              const errText = await testRes.text();
              report.test_gemini = { error: `Gemini API ${testRes.status}: ${errText.slice(0, 500)}`, model };
            } else {
              const geminiData = await testRes.json();
              const candidate = geminiData.candidates?.[0];
              report.test_gemini = {
                model,
                status: "OK",
                response_text: candidate?.content?.parts?.[0]?.text?.slice(0, 200) || "(empty)",
                finish_reason: candidate?.finishReason || "",
                safety_ratings: geminiData.candidates?.[0]?.safetyRatings?.map((r: { category: string; probability: string }) => `${r.category}:${r.probability}`) || [],
              };
            }
          }
        }
      } catch (e) {
        report.test_gemini = { error: String(e) };
      }
    }

    // --- Test Gemini with Layer1-like prompt ---
    if (action === "test_gemini_layer1") {
      try {
        const token = await getAccessToken();
        const jobUrl = `https://run.googleapis.com/v2/projects/${GCP_PROJECT}/locations/${GCP_REGION}/jobs/orchestrate-v2`;
        const jobRes = await fetch(jobUrl, { headers: { Authorization: `Bearer ${token}` } });
        const job = await jobRes.json();
        const envVars = job.template?.template?.containers?.[0]?.env || [];
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        let apiKey = (envVars.find((e: any) => e.name === "GEMINI_API_KEY") as any)?.value || "";
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const secretRef = (envVars.find((e: any) => e.name === "GEMINI_API_KEY") as any)?.valueSource?.secretKeyRef;
        if (!apiKey && secretRef) {
          const sUrl = `https://secretmanager.googleapis.com/v1/projects/${GCP_PROJECT}/secrets/${secretRef.secret}/versions/${secretRef.version || "latest"}:access`;
          const sRes = await fetch(sUrl, { headers: { Authorization: `Bearer ${token}` } });
          if (sRes.ok) { const sd = await sRes.json(); apiKey = Buffer.from(sd.payload?.data || "", "base64").toString("utf-8"); }
        }
        if (!apiKey) { report.test_gemini_layer1 = { error: "No API key" }; }
        else {
          const testPrompt = "あなたは許認可ビジネスの視点から建設業向けビジネスを設計する専門家です。\n\n## 建設業界コンテキスト\n重層下請構造。職人は日給月給。人材不足が最大課題。\n\n## CEO制約\n{\"industry\":\"建設業\",\"channel\":\"Web完結\",\"team\":\"2-5人\",\"budget\":\"初期投資ほぼゼロ\",\"target_monthly_profit\":3000000}\n\n## 軸: 許認可ビジネス（A3）\n## フォーカス: 建設業許可、特定技能、有料職業紹介\n\n建設業で成り立つビジネスモデルの「型」を5個リストアップ。\n\n## 出力形式（JSON配列）\n[{\"type_name\":\"型の名前\",\"description\":\"説明\",\"revenue_model\":\"収益モデル\",\"example\":\"具体例\"}]";
          const gUrl = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${apiKey}`;
          const gRes = await fetch(gUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              contents: [{ parts: [{ text: testPrompt }] }],
              systemInstruction: { parts: [{ text: "あなたは建設業界に精通したビジネスアナリストです。ビジネスモデルの「型」をJSON配列で出力してください。" }] },
              generationConfig: { responseMimeType: "application/json", maxOutputTokens: 16384, temperature: 0.6 },
            }),
          });
          if (!gRes.ok) {
            report.test_gemini_layer1 = { error: `${gRes.status}: ${(await gRes.text()).slice(0, 500)}` };
          } else {
            const data = await gRes.json();
            const cand = data.candidates?.[0];
            const text = cand?.content?.parts?.[0]?.text || "";
            let parsed = null;
            try { parsed = JSON.parse(text); } catch { parsed = null; }
            report.test_gemini_layer1 = {
              status: "OK", response_length: text.length,
              parsed_count: Array.isArray(parsed) ? parsed.length : parsed ? 1 : 0,
              first_type: Array.isArray(parsed) ? parsed[0]?.type_name : "(not array)",
              finish_reason: cand?.finishReason || "",
              prompt_feedback: data.promptFeedback || null,
            };
          }
        }
      } catch (e) { report.test_gemini_layer1 = { error: String(e) }; }
    }

    // --- Deploy code hotfix: override Cloud Run Job command to git-pull latest code ---
    if (action === "deploy_hotfix") {
      try {
        const token = await getAccessToken();
        const jobUrl = `https://run.googleapis.com/v2/projects/${GCP_PROJECT}/locations/${GCP_REGION}/jobs/orchestrate-v2`;

        // 1. Read current job spec
        const jobRes = await fetch(jobUrl, { headers: { Authorization: `Bearer ${token}` } });
        if (!jobRes.ok) {
          report.deploy_hotfix = { error: `Read job: ${jobRes.status}` };
        } else {
          const job = await jobRes.json();
          const container = job.template?.template?.containers?.[0];
          if (!container) {
            report.deploy_hotfix = { error: "No container found in job spec" };
          } else {
            // 2. Build git-pull command prefix
            const gitPullCmd = [
              "echo '=== Hotfix: pulling latest code from GitHub ==='",
              "apt-get update -qq && apt-get install -y -qq git > /dev/null 2>&1 || true",
              "git clone --depth 1 https://github.com/shokunin-san-com/business-automation.git /tmp/latest",
              "cp -r /tmp/latest/scripts/* /app/scripts/",
              "cp -r /tmp/latest/templates/* /app/templates/",
              "[ -f /tmp/latest/run.py ] && cp /tmp/latest/run.py /app/run.py",
              "echo '=== Code updated, starting pipeline ==='",
              "python run.py",
            ].join(" && ");

            // 3. Build clean container spec (only writable fields)
            const cleanContainer: Record<string, unknown> = {
              image: container.image,
              command: ["/bin/bash", "-c"],
              args: [gitPullCmd],
            };
            // Preserve env vars and resources
            if (container.env) cleanContainer.env = container.env;
            if (container.resources) cleanContainer.resources = container.resources;

            // 4. PATCH the job (full job body, no updateMask)
            const patchRes = await fetch(jobUrl, {
              method: "PATCH",
              headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
              body: JSON.stringify({
                template: {
                  template: {
                    containers: [cleanContainer],
                    maxRetries: job.template?.template?.maxRetries,
                    timeout: job.template?.template?.timeout,
                    serviceAccount: job.template?.template?.serviceAccount,
                  },
                  taskCount: job.template?.taskCount,
                },
                launchStage: job.launchStage,
              }),
            });

            if (!patchRes.ok) {
              const errText = await patchRes.text();
              report.deploy_hotfix = { error: `Patch job: ${patchRes.status}: ${errText.slice(0, 500)}` };
            } else {
              const patchData = await patchRes.json();
              report.deploy_hotfix = {
                status: "OK",
                message: "Cloud Run Job updated — will git-pull latest code on next run",
                updateTime: patchData.updateTime || "",
                args_preview: gitPullCmd.slice(0, 200) + "...",
              };
            }
          }
        }
      } catch (e) {
        report.deploy_hotfix = { error: String(e) };
      }
    }

    // --- Revert hotfix: restore original CMD ---
    if (action === "revert_hotfix") {
      try {
        const token = await getAccessToken();
        const jobUrl = `https://run.googleapis.com/v2/projects/${GCP_PROJECT}/locations/${GCP_REGION}/jobs/orchestrate-v2`;
        const jobRes = await fetch(jobUrl, { headers: { Authorization: `Bearer ${token}` } });
        if (!jobRes.ok) {
          report.revert_hotfix = { error: `Read job: ${jobRes.status}` };
        } else {
          const job = await jobRes.json();
          const container = job.template?.template?.containers?.[0];
          if (!container) {
            report.revert_hotfix = { error: "No container found" };
          } else {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const restored = { ...container } as any;
            delete restored.command;
            restored.args = undefined;
            const patchRes = await fetch(`${jobUrl}?updateMask=template.template.containers`, {
              method: "PATCH",
              headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
              body: JSON.stringify({
                template: { template: { containers: [{ ...container, command: [], args: ["python", "run.py"] }] } },
              }),
            });
            if (!patchRes.ok) {
              report.revert_hotfix = { error: `Patch: ${patchRes.status}: ${(await patchRes.text()).slice(0, 500)}` };
            } else {
              report.revert_hotfix = { status: "OK", message: "Restored original CMD: python run.py" };
            }
          }
        }
      } catch (e) {
        report.revert_hotfix = { error: String(e) };
      }
    }

    // --- Task 4: Unpublish all blog articles ---
    if (action === "unpublish_blogs" || action === "all") {
      const count = await batchUpdateColumn(
        "blog_articles",
        "status",
        "unpublished",
        (row) => row.status === "published" || row.status === "draft",
      );

      report.unpublish_blogs = {
        updated: count,
      };
    }

    return NextResponse.json({ ok: true, report });
  } catch (err) {
    console.error("[admin/v4-cleanup] Error:", err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
