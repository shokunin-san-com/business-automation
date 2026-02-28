import { NextRequest, NextResponse } from "next/server";
import { getAllRows, countRows } from "@/lib/sheets";
import { getAccessToken, GCP_PROJECT, GCP_REGION, JOB_MAP } from "@/lib/gcp-auth";

// All scheduler job names
const ALL_SCHEDULERS = Object.values(JOB_MAP).flatMap((j) => j.schedulers);

// ---------------------------------------------------------------------------
// In-memory cache to avoid hitting Google Sheets quota (60 reads/min/user)
// ---------------------------------------------------------------------------
const CACHE_TTL_MS = 15_000; // 15 seconds

interface CacheEntry {
  data: unknown;
  fetchedAt: number;
}

const cache = new Map<string, CacheEntry>();

async function cachedGetAllRows(sheetName: string): Promise<Record<string, string>[]> {
  const now = Date.now();
  const entry = cache.get(`rows:${sheetName}`);
  if (entry && now - entry.fetchedAt < CACHE_TTL_MS) {
    return entry.data as Record<string, string>[];
  }
  const rows = await getAllRows(sheetName);
  cache.set(`rows:${sheetName}`, { data: rows, fetchedAt: now });
  return rows;
}

async function cachedCountRows(sheetName: string): Promise<number> {
  const now = Date.now();
  const entry = cache.get(`count:${sheetName}`);
  if (entry && now - entry.fetchedAt < CACHE_TTL_MS) {
    return entry.data as number;
  }
  const count = await countRows(sheetName);
  cache.set(`count:${sheetName}`, { data: count, fetchedAt: now });
  return count;
}

interface PendingIdea {
  id: string;
  name: string;
  category: string;
  description: string;
  target_audience: string;
  created_at: string;
  offers?: { offerName: string; deliverable: string; price: string }[];
  evidenceCount?: number;
}

/**
 * GET /api/dashboard
 *
 * Reads all data from Google Sheets instead of local filesystem.
 * Uses a 15-second in-memory cache to stay within Sheets API quota.
 * - pipeline_status sheet  -> pipeline status
 * - business_ideas (status=draft) -> pending ideas
 * - lp_content row count   -> LP count
 * - Cloud Scheduler API    -> scheduler states
 * - execution_logs sheet   -> recent execution logs
 */
export async function GET(request: NextRequest) {
  const nocache = request.nextUrl.searchParams.get("nocache") === "1";
  if (nocache) {
    cache.clear();
  }

  const fetchErrors: { section: string; message: string }[] = [];

  try {
    // --- Pipeline status from Sheets ---
    let pipelineRows: Record<string, string>[] = [];
    try {
      pipelineRows = await cachedGetAllRows("pipeline_status");
    } catch (err) {
      fetchErrors.push({ section: "pipeline", message: String(err) });
    }

    const scriptLabels: Record<string, string> = {
      orchestrate_v2: "V2パイプライン",
      "1_lp_generator": "LP生成",
      "2_sns_poster": "SNS投稿",
      "3_form_sales": "フォーム営業",
      "4_analytics_reporter": "分析・改善",
      "5_slack_reporter": "Slackレポート",
      "7_learning_engine": "学習エンジン",
      "9_expansion_engine": "拡張エンジン",
    };

    // Build a lookup from pipeline_status rows
    const statusMap = new Map<string, Record<string, string>>();
    for (const row of pipelineRows) {
      if (row.script_name) statusMap.set(row.script_name, row);
    }

    let lastUpdated = "";
    const pipeline = Object.entries(scriptLabels).map(([key, label]) => {
      const s = statusMap.get(key);
      if (s?.timestamp && s.timestamp > lastUpdated) lastUpdated = s.timestamp;

      let metrics: Record<string, number> = {};
      if (s?.metrics_json) {
        try { metrics = JSON.parse(s.metrics_json); } catch { /* ignore */ }
      }

      return {
        id: key,
        label,
        status: s?.status || "idle",
        detail: s?.detail || "",
        metrics,
        lastRun: s?.timestamp || "",
      };
    });

    // --- LP count from lp_content sheet ---
    let lpCount = 0;
    try {
      lpCount = await cachedCountRows("lp_content");
    } catch (err) {
      fetchErrors.push({ section: "lp", message: String(err) });
    }

    // --- Pending offers from offer_3_log (V2: replaces business_ideas) ---
    // Only show READY runs that haven't been approved/rejected yet
    let pendingIdeas: PendingIdea[] = [];
    try {
      const lpReady = await cachedGetAllRows("lp_ready_log").catch(() => [] as Record<string, string>[]);
      const readyRunIds = new Set(
        lpReady.filter((r) => r.status === "READY").map((r) => r.run_id),
      );

      // Exclude runs already approved or rejected
      const rejectRows = await cachedGetAllRows("ceo_reject_log").catch(() => [] as Record<string, string>[]);
      const decidedRunIds = new Set(
        rejectRows
          .filter((r) => r.type === "run_approve" || r.type === "run_reject")
          .map((r) => r.run_id),
      );

      const pendingRunIds = [...readyRunIds].filter((rid) => !decidedRunIds.has(rid));

      if (pendingRunIds.length > 0) {
        const offers = await cachedGetAllRows("offer_3_log");
        const gateRows = await cachedGetAllRows("gate_decision_log");

        for (const rid of pendingRunIds.slice(-5)) {
          const gate = gateRows.find((g) => g.run_id === rid && g.status === "PASS");
          const ridOffers = offers.filter((o) => o.run_id === rid);

          if (ridOffers.length > 0 || gate) {
            pendingIdeas.push({
              id: rid,
              name: gate?.micro_market || rid.slice(0, 8),
              category: gate?.payer || "",
              description: gate?.blackout_hypothesis || "",
              target_audience: gate?.payer || "",
              created_at: gate?.timestamp || "",
              offers: ridOffers.map((o) => ({
                offerName: o.offer_name || "",
                deliverable: o.deliverable || "",
                price: o.price || "",
              })),
              evidenceCount: (() => {
                try {
                  const urls = JSON.parse(gate?.evidence_urls || "{}");
                  return Object.values(urls).filter(Boolean).length;
                } catch { return 0; }
              })(),
            });
          }
        }
      }
    } catch (err) {
      fetchErrors.push({ section: "pendingIdeas", message: String(err) });
    }

    // --- Scheduler status from Cloud Scheduler API ---
    const schedulerStatus: Record<string, { state: string; schedule: string; nextRun: string }> = {};
    try {
      const token = await getAccessToken();
      const schedulerUrl = `https://cloudscheduler.googleapis.com/v1/projects/${GCP_PROJECT}/locations/${GCP_REGION}/jobs`;
      const schRes = await fetch(schedulerUrl, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (schRes.ok) {
        const schData = await schRes.json();
        const jobs = schData.jobs || [];
        for (const job of jobs) {
          const shortName = job.name?.split("/").pop() || "";
          if (ALL_SCHEDULERS.includes(shortName)) {
            schedulerStatus[shortName] = {
              state: job.state || "ENABLED",
              schedule: job.schedule || "",
              nextRun: job.scheduleTime || "",
            };
          }
        }
      }
    } catch (err) {
      fetchErrors.push({ section: "scheduler", message: String(err) });
    }

    // --- Logs: combine pipeline_status + execution_logs ---
    const pipelineLogs = pipelineRows
      .filter((r) => r.detail)
      .map((r) => ({
        time: r.timestamp || "",
        text: `[${r.script_name}] ${r.status}: ${r.detail}`,
      }));

    let execLogs: { time: string; text: string }[] = [];
    try {
      const execRows = await cachedGetAllRows("execution_logs");
      execLogs = execRows.map((r) => ({
        time: r.timestamp || "",
        text: `[${r.job_name}] ${r.trigger}/${r.status}: ${r.detail}`,
      }));
    } catch { /* sheet may not exist yet */ }

    const logs = [...pipelineLogs, ...execLogs]
      .sort((a, b) => b.time.localeCompare(a.time))
      .slice(0, 100)
      .map((l) => `${l.time} ${l.text}`);

    // --- V2: Gate results, offers, scoring warnings, CEO review status ---
    let latestRunId = "";
    let gateResults: Record<string, string>[] = [];
    let offers: Record<string, string>[] = [];
    let scoringWarnings: string[] = [];
    let ceoReviewNeeded = { market: false, offer: false };
    let lpReadyStatus = "";

    try {
      // Latest run_id from settings_snapshot
      const snapshots = await cachedGetAllRows("settings_snapshot");
      if (snapshots.length > 0) {
        latestRunId = snapshots[snapshots.length - 1].run_id || "";
      }

      if (latestRunId) {
        // Gate results for latest run
        const gateRows = await cachedGetAllRows("gate_decision_log");
        gateResults = gateRows.filter((r) => r.run_id === latestRunId);

        // Offers for latest run
        const offerRows = await cachedGetAllRows("offer_3_log");
        offers = offerRows.filter((r) => r.run_id === latestRunId);

        // CEO review check
        const passMarkets = gateResults.filter((r) => r.status === "PASS");
        const rejectRows = await cachedGetAllRows("ceo_reject_log").catch(() => [] as Record<string, string>[]);
        const rejectedMarkets = new Set(
          rejectRows
            .filter((r) => r.run_id === latestRunId && r.type === "market")
            .map((r) => r.rejected_item),
        );
        const remainingMarkets = passMarkets.filter(
          (m) => !rejectedMarkets.has(m.micro_market),
        );
        ceoReviewNeeded.market = remainingMarkets.length > 1;

        const rejectedOffers = new Set(
          rejectRows
            .filter((r) => r.run_id === latestRunId && r.type === "offer")
            .map((r) => r.rejected_item),
        );
        const remainingOffers = offers.filter(
          (o) => !rejectedOffers.has(o.offer_name),
        );
        ceoReviewNeeded.offer = remainingOffers.length > 1;

        // LP ready status
        const lpReady = await cachedGetAllRows("lp_ready_log").catch(() => [] as Record<string, string>[]);
        const lpForRun = lpReady.filter((r) => r.run_id === latestRunId);
        if (lpForRun.length > 0) {
          lpReadyStatus = lpForRun[lpForRun.length - 1].status || "";
        }
      }

      // Scoring warnings: check if deprecated scoring keys still exist in settings
      const settingsRows = await cachedGetAllRows("settings");
      const deprecatedKeys = [
        "exploration_scoring_weights",
        "orchestrator_min_score_threshold",
        "orchestrator_auto_approve_n",
        "orchestrator_auto_approve",
      ];
      for (const row of settingsRows) {
        if (deprecatedKeys.includes(row.key) && row.value) {
          scoringWarnings.push(
            `設定 "${row.key}" はV2で廃止済みです。値 "${row.value}" が残っています。削除してください。`,
          );
        }
      }
    } catch (err) {
      fetchErrors.push({ section: "v2", message: String(err) });
    }

    // --- Downstream metrics: inquiry + deal pipeline ---
    let downstream = {
      totalInquiries: 0,
      newInquiries: 0,
      qualifiedInquiries: 0,
      totalDeals: 0,
      activeDeals: 0,
      wonDeals: 0,
      lostDeals: 0,
      totalDealValue: 0,
      dealRate: 0,
      funnel: [] as { stage: string; count: number }[],
    };

    try {
      const inquiries = await cachedGetAllRows("inquiry_log");
      const deals = await cachedGetAllRows("deal_pipeline");

      downstream.totalInquiries = inquiries.length;
      downstream.newInquiries = inquiries.filter((r) => r.status === "new").length;
      downstream.qualifiedInquiries = inquiries.filter((r) => r.status === "qualified").length;
      downstream.totalDeals = deals.length;
      downstream.wonDeals = deals.filter((r) => r.stage === "won").length;
      downstream.lostDeals = deals.filter((r) => r.stage === "lost").length;
      downstream.activeDeals = deals.filter((r) => !["won", "lost"].includes(r.stage)).length;
      downstream.totalDealValue = deals
        .filter((r) => r.stage === "won")
        .reduce((sum, r) => sum + (parseFloat(r.deal_value) || 0), 0);
      downstream.dealRate =
        downstream.totalInquiries > 0
          ? Math.round((downstream.wonDeals / downstream.totalInquiries) * 100) / 100
          : 0;

      // Funnel counts
      const stages = ["inquiry", "qualification", "proposal", "negotiation", "won", "lost"];
      downstream.funnel = stages.map((stage) => ({
        stage,
        count: deals.filter((r) => r.stage === stage).length,
      }));
    } catch (err) {
      fetchErrors.push({ section: "downstream", message: String(err) });
    }

    // --- Expansion: winning patterns ---
    let expansion = {
      totalPatterns: 0,
      activePatterns: 0,
      scalingPatterns: 0,
      patterns: [] as Record<string, string>[],
    };

    try {
      const patterns = await cachedGetAllRows("winning_patterns");
      expansion.totalPatterns = patterns.length;
      expansion.activePatterns = patterns.filter(
        (r) => ["detected", "validated", "scaling"].includes(r.status),
      ).length;
      expansion.scalingPatterns = patterns.filter((r) => r.status === "scaling").length;
      expansion.patterns = patterns
        .filter((r) => r.status !== "archived")
        .slice(-10);
    } catch (err) {
      fetchErrors.push({ section: "expansion", message: String(err) });
    }

    // --- Active Businesses: aggregate per-business stats ---
    interface ActiveBusinessEntry {
      runId: string;
      marketName: string;
      payer: string;
      offers: { offerName: string; deliverable: string; price: string }[];
      gatePassedAt: string;
      lpReady: boolean;
      lpUrls: string[];
      stats: {
        lpCount: number;
        snsPostCount: number;
        formSubmitCount: number;
        formResponseCount: number;
        blogArticleCount: number;
        inquiryCount: number;
        dealWonCount: number;
        dealLostCount: number;
      };
    }

    let activeBusinesses: ActiveBusinessEntry[] = [];

    try {
      const lpReady = await cachedGetAllRows("lp_ready_log");
      const readyRunIds = lpReady
        .filter((r) => r.status === "READY")
        .map((r) => r.run_id)
        .filter(Boolean);

      if (readyRunIds.length > 0) {
        const gateRows = await cachedGetAllRows("gate_decision_log");
        const offerRows = await cachedGetAllRows("offer_3_log");
        const lpContent = await cachedGetAllRows("lp_content");
        const snsPosts = await cachedGetAllRows("sns_posts");
        const formTargets = await cachedGetAllRows("form_sales_targets");
        const blogArticles = await cachedGetAllRows("blog_articles");
        const inquiryRows = await cachedGetAllRows("inquiry_log");
        const dealRows = await cachedGetAllRows("deal_pipeline");

        for (const rid of readyRunIds) {
          const gate = gateRows.find((g) => g.run_id === rid && g.status === "PASS");
          if (!gate) continue;

          const bizOffers = offerRows
            .filter((o) => o.run_id === rid)
            .map((o) => ({
              offerName: o.offer_name || "",
              deliverable: o.deliverable || "",
              price: o.price || "",
            }));

          const bizLps = lpContent.filter((r) => r.business_id === rid);
          const lpUrls = bizLps.map((r) => `https://lp-app-pi.vercel.app/lp/${encodeURIComponent(r.business_id)}`);

          const lpCountBiz = bizLps.length;
          const snsPostCount = snsPosts.filter((r) => r.business_id === rid).length;
          const formSubmitCount = formTargets.filter(
            (r) => r.business_id === rid && ["sent", "dry_run"].includes(r.status),
          ).length;
          const formResponseCount = formTargets.filter(
            (r) => r.business_id === rid && r.response && r.response !== "",
          ).length;
          const blogArticleCount = blogArticles.filter(
            (r) => r.business_id === rid && r.status === "published",
          ).length;
          const inquiryCount = inquiryRows.filter(
            (r) => r.business_id === rid || r.run_id === rid,
          ).length;
          const dealWonCount = dealRows.filter(
            (r) => (r.business_id === rid || r.run_id === rid) && r.stage === "won",
          ).length;
          const dealLostCount = dealRows.filter(
            (r) => (r.business_id === rid || r.run_id === rid) && r.stage === "lost",
          ).length;

          activeBusinesses.push({
            runId: rid,
            marketName: gate.micro_market || rid.slice(0, 8),
            payer: gate.payer || "",
            offers: bizOffers,
            gatePassedAt: gate.timestamp || "",
            lpReady: true,
            lpUrls,
            stats: {
              lpCount: lpCountBiz,
              snsPostCount,
              formSubmitCount,
              formResponseCount,
              blogArticleCount,
              inquiryCount,
              dealWonCount,
              dealLostCount,
            },
          });
        }
      }
    } catch (err) {
      fetchErrors.push({ section: "activeBusinesses", message: String(err) });
    }

    // --- Blog stats ---
    let blogStats = { total: 0, published: 0, draft: 0 };
    try {
      const articles = await cachedGetAllRows("blog_articles");
      blogStats.total = articles.length;
      blogStats.published = articles.filter((r) => r.status === "published").length;
      blogStats.draft = articles.filter((r) => r.status === "draft").length;
    } catch (err) {
      fetchErrors.push({ section: "blog", message: String(err) });
    }

    return NextResponse.json({
      pipeline,
      lpCount,
      logs,
      lastUpdated,
      pendingIdeas,
      schedulerStatus,
      v2: {
        latestRunId,
        gateResults,
        offers,
        scoringWarnings,
        ceoReviewNeeded,
        lpReadyStatus,
      },
      downstream,
      expansion,
      activeBusinesses,
      fetchErrors,
      blogStats,
    });
  } catch (err) {
    console.error("Dashboard API error:", err);
    // Return empty state so the dashboard still renders
    return NextResponse.json({
      pipeline: [],
      lpCount: 0,
      logs: [],
      lastUpdated: "",
      pendingIdeas: [],
      schedulerStatus: {},
      v2: {
        latestRunId: "",
        gateResults: [],
        offers: [],
        scoringWarnings: [],
        ceoReviewNeeded: { market: false, offer: false },
        lpReadyStatus: "",
      },
      downstream: {
        totalInquiries: 0,
        newInquiries: 0,
        qualifiedInquiries: 0,
        totalDeals: 0,
        activeDeals: 0,
        wonDeals: 0,
        lostDeals: 0,
        totalDealValue: 0,
        dealRate: 0,
        funnel: [],
      },
      expansion: {
        totalPatterns: 0,
        activePatterns: 0,
        scalingPatterns: 0,
        patterns: [],
      },
      activeBusinesses: [],
      fetchErrors: [{ section: "global", message: String(err) }],
      blogStats: { total: 0, published: 0, draft: 0 },
    });
  }
}
