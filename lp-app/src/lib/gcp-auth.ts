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
let _chatAuthClient: InstanceType<typeof google.auth.GoogleAuth> | null = null;

function getCredentials() {
  const saJson = process.env.GOOGLE_SERVICE_ACCOUNT_JSON;
  if (saJson) return { credentials: JSON.parse(saJson) };

  const localPath = path.join(process.cwd(), "..", "credentials", "service_account.json");
  if (fs.existsSync(localPath)) return { keyFile: localPath };

  throw new Error("No Google credentials found");
}

function getAuth() {
  if (_authClient) return _authClient;
  _authClient = new google.auth.GoogleAuth({
    ...getCredentials(),
    scopes: ["https://www.googleapis.com/auth/cloud-platform"],
  });
  return _authClient;
}

function getChatAuth() {
  if (_chatAuthClient) return _chatAuthClient;
  _chatAuthClient = new google.auth.GoogleAuth({
    ...getCredentials(),
    scopes: [
      "https://www.googleapis.com/auth/chat.bot",
      "https://www.googleapis.com/auth/chat.messages.create",
    ],
  });
  return _chatAuthClient;
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
 * Get a valid OAuth2 access token for Google Chat API calls.
 */
export async function getChatAccessToken(): Promise<string> {
  const auth = getChatAuth();
  const client = await auth.getClient();
  const tokenRes = await client.getAccessToken();
  if (!tokenRes.token) throw new Error("Failed to get Chat access token");
  return tokenRes.token;
}

/**
 * Get a user OAuth2 access token for Workspace Events API.
 * Uses refresh_token flow (no browser interaction needed).
 */
export async function getWorkspaceEventsToken(): Promise<string> {
  const clientId = process.env.WORKSPACE_OAUTH_CLIENT_ID;
  const clientSecret = process.env.WORKSPACE_OAUTH_CLIENT_SECRET;
  const refreshToken = process.env.WORKSPACE_OAUTH_REFRESH_TOKEN;

  if (!clientId || !clientSecret || !refreshToken) {
    throw new Error("Missing WORKSPACE_OAUTH_* environment variables");
  }

  const res = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: clientId,
      client_secret: clientSecret,
      refresh_token: refreshToken,
      grant_type: "refresh_token",
    }),
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Failed to refresh workspace events token: ${res.status} ${err}`);
  }

  const data = await res.json();
  return data.access_token;
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
  "8_ads_creator": {
    jobId: "ads-creator",
    schedulers: ["schedule-ads-creator"],
  },
  orchestrate_abc0: {
    jobId: "agent-orchestrator",
    schedulers: [],
  },
  orchestrate_v2: {
    jobId: "orchestrate-v2",
    schedulers: [],
  },
};
