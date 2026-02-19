/**
 * GCP Authentication helper — generates OAuth2 access tokens from service account.
 * Used by Cloud Run Jobs API and Cloud Scheduler API.
 */

import { google } from "googleapis";
import fs from "fs";
import path from "path";

const GCP_PROJECT = process.env.GCP_PROJECT_ID || "marketprobe-automation";
const GCP_REGION = process.env.GCP_REGION || "asia-northeast1";

export { GCP_PROJECT, GCP_REGION };

let _authClient: InstanceType<typeof google.auth.GoogleAuth> | null = null;

function getAuth() {
  if (_authClient) return _authClient;

  const saJson = process.env.GOOGLE_SERVICE_ACCOUNT_JSON;
  if (saJson) {
    const parsed = JSON.parse(saJson);
    _authClient = new google.auth.GoogleAuth({
      credentials: parsed,
      scopes: ["https://www.googleapis.com/auth/cloud-platform"],
    });
  } else {
    const localPath = path.join(process.cwd(), "..", "credentials", "service_account.json");
    if (fs.existsSync(localPath)) {
      _authClient = new google.auth.GoogleAuth({
        keyFile: localPath,
        scopes: ["https://www.googleapis.com/auth/cloud-platform"],
      });
    } else {
      throw new Error("No Google credentials found");
    }
  }

  return _authClient;
}

/**
 * Get a valid OAuth2 access token for GCP API calls.
 */
export async function getAccessToken(): Promise<string> {
  const auth = getAuth();
  const client = await auth.getClient();
  const tokenRes = await client.getAccessToken();
  if (!tokenRes.token) throw new Error("Failed to get access token");
  return tokenRes.token;
}

/**
 * Job name to Cloud Run Job ID mapping.
 */
export const JOB_MAP: Record<string, { jobId: string; schedulers: string[] }> = {
  A_market_research: {
    jobId: "market-research",
    schedulers: ["schedule-market-research"],
  },
  B_market_selection: {
    jobId: "market-selection",
    schedulers: ["schedule-market-selection"],
  },
  C_competitor_analysis: {
    jobId: "competitor-analysis",
    schedulers: ["schedule-competitor-analysis"],
  },
  "0_idea_generator": {
    jobId: "idea-generator",
    schedulers: ["schedule-idea-generator"],
  },
  "1_lp_generator": {
    jobId: "lp-generator",
    schedulers: ["schedule-lp-generator"],
  },
  "2_sns_poster": {
    jobId: "sns-poster",
    schedulers: ["schedule-sns-morning", "schedule-sns-evening"],
  },
  "3_form_sales": {
    jobId: "form-sales",
    schedulers: ["schedule-form-sales"],
  },
  "4_analytics_reporter": {
    jobId: "analytics-reporter",
    schedulers: ["schedule-analytics"],
  },
  "5_slack_reporter": {
    jobId: "slack-reporter",
    schedulers: ["schedule-slack-report"],
  },
  "6_ads_monitor": {
    jobId: "ads-monitor",
    schedulers: ["schedule-ads-monitor"],
  },
  "7_learning_engine": {
    jobId: "learning-engine",
    schedulers: ["schedule-learning-engine"],
  },
};
