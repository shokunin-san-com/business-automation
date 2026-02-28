export interface ScriptInfo {
  id: string;
  label: string;
  status: string;
  detail: string;
  metrics: Record<string, number>;
  lastRun: string;
}

export interface PendingIdea {
  id: string;
  name: string;
  category: string;
  description: string;
  target_audience: string;
  created_at: string;
  offers?: { offerName: string; deliverable: string; price: string }[];
  evidenceCount?: number;
}

export interface SchedulerInfo {
  state: string;
  schedule: string;
  nextRun: string;
}

export interface V2Data {
  latestRunId: string;
  gateResults: Record<string, string>[];
  offers: Record<string, string>[];
  scoringWarnings: string[];
  ceoReviewNeeded: { market: boolean; offer: boolean };
  lpReadyStatus: string;
}

export interface DownstreamData {
  totalInquiries: number;
  newInquiries: number;
  qualifiedInquiries: number;
  totalDeals: number;
  activeDeals: number;
  wonDeals: number;
  lostDeals: number;
  totalDealValue: number;
  dealRate: number;
  funnel: { stage: string; count: number }[];
}

export interface ExpansionData {
  totalPatterns: number;
  activePatterns: number;
  scalingPatterns: number;
  patterns: Record<string, string>[];
}

export interface ActiveBusiness {
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

export interface DataFetchError {
  section: string;
  message: string;
}

export interface DashboardData {
  pipeline: ScriptInfo[];
  lpCount: number;
  logs: string[];
  lastUpdated: string;
  pendingIdeas?: PendingIdea[];
  schedulerStatus?: Record<string, SchedulerInfo>;
  v2?: V2Data;
  downstream?: DownstreamData;
  expansion?: ExpansionData;
  activeBusinesses: ActiveBusiness[];
  fetchErrors: DataFetchError[];
  blogStats: { total: number; published: number; draft: number };
}

export interface KnowledgeDoc {
  id: string;
  filename: string;
  title: string;
  summary: string;
  chapterCount: number;
  keyFrameworks: string[];
  applicableTo: string;
  uploadedAt: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}
