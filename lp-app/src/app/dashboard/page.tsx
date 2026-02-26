"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import AppShell from "../../components/AppShell";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */
interface ScriptInfo {
  id: string;
  label: string;
  status: string;
  detail: string;
  metrics: Record<string, number>;
  lastRun: string;
}

interface PendingIdea {
  id: string;
  name: string;
  category: string;
  description: string;
  target_audience: string;
  created_at: string;
}

interface SchedulerInfo {
  state: string;
  schedule: string;
  nextRun: string;
}

interface V2Data {
  latestRunId: string;
  gateResults: Record<string, string>[];
  offers: Record<string, string>[];
  scoringWarnings: string[];
  ceoReviewNeeded: { market: boolean; offer: boolean };
  lpReadyStatus: string;
}

interface DownstreamData {
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

interface ExpansionData {
  totalPatterns: number;
  activePatterns: number;
  scalingPatterns: number;
  patterns: Record<string, string>[];
}

interface DashboardData {
  pipeline: ScriptInfo[];
  lpCount: number;
  logs: string[];
  lastUpdated: string;
  pendingIdeas?: PendingIdea[];
  schedulerStatus?: Record<string, SchedulerInfo>;
  v2?: V2Data;
  downstream?: DownstreamData;
  expansion?: ExpansionData;
}

interface KnowledgeDoc {
  id: string;
  filename: string;
  title: string;
  summary: string;
  chapterCount: number;
  keyFrameworks: string[];
  applicableTo: string;
  uploadedAt: string;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */
const STATUS_DOT: Record<string, string> = {
  running: "bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,.6)] animate-pulse",
  success: "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,.5)]",
  error: "bg-red-500 shadow-[0_0_6px_rgba(239,68,68,.5)]",
  idle: "bg-white/20",
};

const STATUS_BADGE: Record<string, { bg: string; text: string; label: string }> = {
  running: { bg: "bg-blue-500/15 border-blue-500/30", text: "text-blue-400", label: "実行中" },
  success: { bg: "bg-emerald-500/15 border-emerald-500/30", text: "text-emerald-400", label: "完了" },
  error: { bg: "bg-red-500/15 border-red-500/30", text: "text-red-400", label: "エラー" },
  idle: { bg: "bg-white/5 border-white/10", text: "text-white/40", label: "待機中" },
};

const PIPELINE_META: Record<string, { icon: string; schedule: string; schedulers: string[] }> = {
  orchestrate_v2: { icon: "\u{1F52C}", schedule: "", schedulers: [] },
  "1_lp_generator": { icon: "\u{1F680}", schedule: "毎日 09:00", schedulers: ["schedule-lp-generator"] },
  "2_sns_poster": { icon: "\u{1F4E2}", schedule: "毎日 10:00 / 18:00", schedulers: ["schedule-sns-morning", "schedule-sns-evening"] },
  "3_form_sales": { icon: "\u2709\uFE0F", schedule: "平日 11:00", schedulers: ["schedule-form-sales"] },
  "4_analytics_reporter": { icon: "\u{1F4C8}", schedule: "毎日 01:00", schedulers: ["schedule-analytics"] },
  "5_slack_reporter": { icon: "\u{1F4AC}", schedule: "毎週月曜 08:00", schedulers: ["schedule-slack-report"] },
  "7_learning_engine": { icon: "\u{1F9E0}", schedule: "毎日 19:00", schedulers: ["schedule-learning-engine"] },
  "9_expansion_engine": { icon: "\u{1F680}", schedule: "毎日 03:00", schedulers: ["schedule-expansion-engine"] },
};

/** Human-readable suffix for individual Cloud Scheduler job names */
const SCHEDULER_LABEL: Record<string, string> = {
  "schedule-sns-morning": "朝",
  "schedule-sns-evening": "夕",
};

const SCHEDULE_PRESETS = [
  { label: "毎日 6:00", cron: "0 6 * * *" },
  { label: "毎日 9:00", cron: "0 9 * * *" },
  { label: "6時間毎", cron: "0 */6 * * *" },
  { label: "12時間毎", cron: "0 */12 * * *" },
  { label: "毎週月曜 8:00", cron: "0 8 * * 1" },
];

function cronToJapanese(cron: string): string {
  if (!cron) return "";
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return cron;
  const [minute, hour, day, month, weekday] = parts;

  const weekdayNames: Record<string, string> = {
    "0": "日", "1": "月", "2": "火", "3": "水", "4": "木", "5": "金", "6": "土", "7": "日",
  };

  // Every N hours
  if (hour.startsWith("*/") && minute === "0" && day === "*" && month === "*" && weekday === "*") {
    return `${hour.slice(2)}時間毎`;
  }
  // Daily at specific time
  if (day === "*" && month === "*" && weekday === "*" && !hour.includes("/") && !minute.includes("/")) {
    return `毎日 ${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
  }
  // Weekday specific
  if (day === "*" && month === "*" && weekday !== "*" && !hour.includes("/")) {
    const dayName = weekdayNames[weekday] || weekday;
    return `毎週${dayName}曜 ${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
  }
  // Weekdays (1-5)
  if (day === "*" && month === "*" && weekday === "1-5" && !hour.includes("/")) {
    return `平日 ${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
  }
  return cron;
}

function formatTime(iso: string): string {
  if (!iso) return "\u2014";
  const d = new Date(iso);
  return d.toLocaleString("ja-JP", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function relativeTime(iso: string): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "たった今";
  if (mins < 60) return `${mins}分前`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}時間前`;
  return `${Math.floor(hrs / 24)}日前`;
}

/* ------------------------------------------------------------------ */
/*  Dashboard Page                                                     */
/* ------------------------------------------------------------------ */
export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [activeTab, setActiveTab] = useState<"pipeline" | "logs" | "knowledge" | "feedback">("pipeline");
  const [approving, setApproving] = useState<string | null>(null);
  const [executing, setExecuting] = useState<string | null>(null);
  const [togglingScheduler, setTogglingScheduler] = useState<string | null>(null);
  const [globalToggling, setGlobalToggling] = useState(false);
  const [scheduleEditTarget, setScheduleEditTarget] = useState<{
    schedulerName: string;
    scriptLabel: string;
    currentCron: string;
  } | null>(null);
  const [scheduleEditCron, setScheduleEditCron] = useState("");
  const [scheduleEditSaving, setScheduleEditSaving] = useState(false);
  const logEndRef = useRef<HTMLDivElement>(null);

  // Knowledge state
  const [knowledgeDocs, setKnowledgeDocs] = useState<KnowledgeDoc[]>([]);
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Feedback state
  const [feedbackMessages, setFeedbackMessages] = useState<ChatMessage[]>([]);
  const [feedbackInput, setFeedbackInput] = useState("");
  const [feedbackLoading, setFeedbackLoading] = useState(false);
  const [feedbackMemories, setFeedbackMemories] = useState<{
    id: string; type: string; source: string; category: string;
    content: string; priority: string; createdAt: string;
  }[]>([]);
  const [feedbackPerf, setFeedbackPerf] = useState<{
    businessId: string; latestScore: number; avgScore: number;
    latestPV: number; latestCVR: number;
  }[]>([]);
  const feedbackEndRef = useRef<HTMLDivElement>(null);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch("/api/dashboard");
      if (res.ok) setData(await res.json());
    } catch {
      /* network error */
    }
  }, []);

  useEffect(() => {
    fetchData();
    if (!autoRefresh) return;
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData, autoRefresh]);

  // Fetch knowledge docs / feedback when tab is selected
  useEffect(() => {
    if (activeTab === "knowledge") {
      fetchKnowledge();
    }
    if (activeTab === "feedback") {
      fetchFeedbackData();
    }
  }, [activeTab]);

  // Scroll chat to bottom
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  useEffect(() => {
    feedbackEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [feedbackMessages]);

  const fetchKnowledge = async () => {
    setKnowledgeLoading(true);
    try {
      const res = await fetch("/api/knowledge");
      if (res.ok) {
        const d = await res.json();
        setKnowledgeDocs(d.documents || []);
      }
    } catch { /* ignore */ }
    finally { setKnowledgeLoading(false); }
  };

  const handleApprove = async (ideaId: string, action: "approve" | "reject") => {
    setApproving(ideaId);
    try {
      await fetch("/api/slack/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idea_id: ideaId, action }),
      });
      await fetchData();
    } finally {
      setApproving(null);
    }
  };

  const handleExecute = async (scriptId: string) => {
    setExecuting(scriptId);
    try {
      const res = await fetch("/api/dashboard/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scriptId }),
      });
      const result = await res.json();
      if (!res.ok) console.error("Execute failed:", result);
      await fetchData();
    } catch (err) {
      console.error("Execute error:", err);
    } finally {
      setExecuting(null);
    }
  };

  const handleSchedulerToggle = async (schedulerName: string, currentState: string) => {
    setTogglingScheduler(schedulerName);
    try {
      const action = currentState === "ENABLED" ? "pause" : "resume";
      await fetch("/api/dashboard/scheduler", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scheduler: schedulerName, action }),
      });
      await fetchData();
    } catch (err) {
      console.error("Scheduler toggle error:", err);
    } finally {
      setTogglingScheduler(null);
    }
  };

  const handleGlobalToggle = async (action: "pause_all" | "resume_all") => {
    setGlobalToggling(true);
    try {
      await fetch("/api/dashboard/scheduler", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      await fetchData();
    } catch (err) {
      console.error("Global toggle error:", err);
    } finally {
      setGlobalToggling(false);
    }
  };

  const handleScheduleSave = async () => {
    if (!scheduleEditTarget || !scheduleEditCron.trim()) return;
    setScheduleEditSaving(true);
    try {
      const res = await fetch("/api/dashboard/scheduler", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jobId: scheduleEditTarget.schedulerName,
          schedule: scheduleEditCron.trim(),
        }),
      });
      if (res.ok) {
        setScheduleEditTarget(null);
        await fetchData();
      } else {
        const err = await res.json();
        alert(err.error || "スケジュール更新に失敗しました");
      }
    } catch (err) {
      console.error("Schedule edit error:", err);
      alert("スケジュール更新に失敗しました");
    } finally {
      setScheduleEditSaving(false);
    }
  };

  /* --- Feedback functions --- */
  const fetchFeedbackData = async () => {
    try {
      const res = await fetch("/api/feedback");
      if (res.ok) {
        const d = await res.json();
        setFeedbackMemories(d.memories || []);
        setFeedbackPerf(d.performanceSummary || []);
      }
    } catch { /* ignore */ }
  };

  const handleFeedbackSend = async () => {
    if (!feedbackInput.trim() || feedbackLoading) return;

    const userMessage = feedbackInput.trim();
    setFeedbackInput("");
    setFeedbackMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    setFeedbackLoading(true);

    try {
      const res = await fetch("/api/feedback/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMessage }),
      });

      if (!res.ok) {
        setFeedbackMessages((prev) => [
          ...prev,
          { role: "assistant", content: "\u30A8\u30E9\u30FC\u304C\u767A\u751F\u3057\u307E\u3057\u305F\u3002" },
        ]);
        return;
      }

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let assistantContent = "";

      setFeedbackMessages((prev) => [...prev, { role: "assistant", content: "" }]);

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split("\n");

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              const payload = line.slice(6);
              if (payload === "[DONE]") break;
              try {
                const parsed = JSON.parse(payload);
                if (parsed.text) {
                  assistantContent += parsed.text;
                  setFeedbackMessages((prev) => {
                    const updated = [...prev];
                    updated[updated.length - 1] = {
                      role: "assistant",
                      content: assistantContent,
                    };
                    return updated;
                  });
                }
                if (parsed.directive_saved) {
                  // Refresh memories after directive saved
                  setTimeout(fetchFeedbackData, 500);
                }
              } catch { /* partial JSON */ }
            }
          }
        }
      }
    } catch (err) {
      console.error("Feedback chat error:", err);
      setFeedbackMessages((prev) => [
        ...prev,
        { role: "assistant", content: "\u901A\u4FE1\u30A8\u30E9\u30FC\u304C\u767A\u751F\u3057\u307E\u3057\u305F\u3002" },
      ]);
    } finally {
      setFeedbackLoading(false);
    }
  };

  const handleSupersede = async (memoryId: string) => {
    try {
      await fetch(`/api/feedback?id=${memoryId}`, { method: "DELETE" });
      await fetchFeedbackData();
    } catch (err) {
      console.error("Supersede error:", err);
    }
  };

  /* --- Upload PDF --- */
  const handleFileUpload = async (file: File) => {
    const MAX_SIZE_MB = 4;
    if (file.size > MAX_SIZE_MB * 1024 * 1024) {
      alert(
        `ファイルが大きすぎます（${(file.size / 1024 / 1024).toFixed(1)}MB）。\n\n` +
        `Web UIは${MAX_SIZE_MB}MBまで対応です。\n` +
        `大きいファイルはターミナルからアップロードしてください:\n\n` +
        `  python3 scripts/upload_knowledge.py references/${file.name}`
      );
      return;
    }

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch("/api/knowledge", {
        method: "POST",
        body: formData,
      });
      const result = await res.json();
      if (res.ok) {
        await fetchKnowledge();
      } else {
        console.error("Upload failed:", result);
        alert(result.error || "アップロードに失敗しました");
      }
    } catch (err) {
      console.error("Upload error:", err);
      alert("アップロード中にエラーが発生しました。ファイルが大きすぎるか、接続がタイムアウトした可能性があります。\n\n大きいファイルはターミナルから:\npython3 scripts/upload_knowledge.py references/" + file.name);
    } finally {
      setUploading(false);
    }
  };

  /* --- Chat with knowledge base --- */
  const handleChatSend = async () => {
    if (!chatInput.trim() || chatLoading) return;

    const userMessage = chatInput.trim();
    setChatInput("");
    setChatMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    setChatLoading(true);

    try {
      const res = await fetch("/api/knowledge/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMessage }),
      });

      if (!res.ok) {
        setChatMessages((prev) => [
          ...prev,
          { role: "assistant", content: "\u30A8\u30E9\u30FC\u304C\u767A\u751F\u3057\u307E\u3057\u305F\u3002\u3082\u3046\u4E00\u5EA6\u304A\u8A66\u3057\u304F\u3060\u3055\u3044\u3002" },
        ]);
        return;
      }

      // Stream the response
      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let assistantContent = "";

      setChatMessages((prev) => [...prev, { role: "assistant", content: "" }]);

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split("\n");

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              const payload = line.slice(6);
              if (payload === "[DONE]") break;
              try {
                const parsed = JSON.parse(payload);
                if (parsed.text) {
                  assistantContent += parsed.text;
                  setChatMessages((prev) => {
                    const updated = [...prev];
                    updated[updated.length - 1] = {
                      role: "assistant",
                      content: assistantContent,
                    };
                    return updated;
                  });
                }
              } catch { /* partial JSON */ }
            }
          }
        }
      }
    } catch (err) {
      console.error("Chat error:", err);
      setChatMessages((prev) => [
        ...prev,
        { role: "assistant", content: "\u901A\u4FE1\u30A8\u30E9\u30FC\u304C\u767A\u751F\u3057\u307E\u3057\u305F\u3002" },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  /* --- Loading state --- */
  if (!data) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#0a0a0f]">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-blue-500" />
          <p className="text-sm text-white/40 tracking-wide">ダッシュボードを読み込み中...</p>
        </div>
      </div>
    );
  }

  const runningCount = data.pipeline.filter((s) => s.status === "running").length;
  const errorCount = data.pipeline.filter((s) => s.status === "error").length;
  const successCount = data.pipeline.filter((s) => s.status === "success").length;
  const pendingIdeas = data.pendingIdeas || [];
  const schedulerStatus = data.schedulerStatus || {};

  const allSchedulerNames = Object.values(PIPELINE_META).flatMap((m) => m.schedulers);
  const enabledSchedulers = allSchedulerNames.filter(
    (name) => schedulerStatus[name]?.state === "ENABLED"
  ).length;
  const allEnabled = enabledSchedulers === allSchedulerNames.length;
  const allPaused = enabledSchedulers === 0;

  return (
    <AppShell lpCount={data.lpCount}>
      {/* Top Bar */}
      <header className="sticky top-0 z-30 hidden lg:flex h-14 items-center justify-between border-b border-white/[.06] bg-[#0a0a0f]/80 px-6 backdrop-blur-xl">
        <div className="flex items-center gap-3">
          <h1 className="text-sm font-medium text-white/60">ダッシュボード</h1>
          {data.lastUpdated && (
            <span className="text-[11px] text-white/20">
              最終更新 {relativeTime(data.lastUpdated)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {runningCount > 0 && (
            <div className="flex items-center gap-1.5 rounded-full bg-blue-500/10 px-2.5 py-1 text-[11px] text-blue-400 border border-blue-500/20">
              <span className="h-1.5 w-1.5 rounded-full bg-blue-500 animate-pulse" />
              {runningCount}件 実行中
            </div>
          )}
          {errorCount > 0 && (
            <div className="flex items-center gap-1.5 rounded-full bg-red-500/10 px-2.5 py-1 text-[11px] text-red-400 border border-red-500/20">
              <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
              {errorCount}件 エラー
            </div>
          )}
          <button
            onClick={() => setAutoRefresh((v) => !v)}
            className={`relative h-6 w-10 rounded-full transition-colors ${
              autoRefresh ? "bg-blue-600" : "bg-white/10"
            }`}
          >
            <span
              className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform ${
                autoRefresh ? "translate-x-[18px]" : "translate-x-0.5"
              }`}
            />
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-6 p-6">
          {/* ---- Pending Approval Banner ---- */}
          {pendingIdeas.length > 0 && (
            <section className="rounded-2xl border border-amber-500/20 bg-gradient-to-r from-amber-500/[.06] to-orange-500/[.04] p-5">
              <div className="mb-3 flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-amber-500/20 text-[10px]">{"\u23F3"}</span>
                <h2 className="text-sm font-semibold text-amber-300">{"\u627F\u8A8D\u5F85\u3061"} {"\u2014"} {pendingIdeas.length}{"\u4EF6\u306E\u4E8B\u696D\u6848"}</h2>
              </div>
              <div className="space-y-2.5">
                {pendingIdeas.map((idea) => (
                  <div key={idea.id} className="flex items-start gap-4 rounded-xl bg-black/30 p-4">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-sm">{idea.name}</p>
                      <p className="mt-0.5 text-xs text-white/40 line-clamp-2">{idea.description}</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <span className="rounded-md bg-white/5 px-2 py-0.5 text-[10px] text-white/50">{idea.category}</span>
                        <span className="rounded-md bg-white/5 px-2 py-0.5 text-[10px] text-white/50">{idea.target_audience}</span>
                      </div>
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <button
                        onClick={() => handleApprove(idea.id, "approve")}
                        disabled={approving === idea.id}
                        className="rounded-lg bg-emerald-600 px-3.5 py-1.5 text-xs font-medium text-white transition-all hover:bg-emerald-500 disabled:opacity-50"
                      >
                        {approving === idea.id ? "..." : "\u627F\u8A8D"}
                      </button>
                      <button
                        onClick={() => handleApprove(idea.id, "reject")}
                        disabled={approving === idea.id}
                        className="rounded-lg bg-white/5 px-3.5 py-1.5 text-xs font-medium text-white/60 transition-all hover:bg-white/10 disabled:opacity-50"
                      >
                        {"\u5374\u4E0B"}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* ---- KPI Cards ---- */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <KPICard label="問い合わせ" value={data.downstream?.totalInquiries ?? 0} trend={null} color="blue" />
            <KPICard
              label="成約率"
              value={data.downstream?.dealRate ? `${(data.downstream.dealRate * 100).toFixed(0)}%` : "0%"}
              trend={null}
              color="emerald"
            />
            <KPICard
              label="V2ゲート通過"
              value={data.pipeline.find((s) => s.id === "orchestrate_v2")?.metrics?.a1d_passed ?? "\u2014"}
              trend={null}
              color="orange"
            />
            <KPICard
              label="オファー数"
              value={data.pipeline.find((s) => s.id === "orchestrate_v2")?.metrics?.offers_generated ?? "\u2014"}
              trend={null}
              color="pink"
            />
            <KPICard
              label="勝ちパターン"
              value={data.expansion?.activePatterns ?? 0}
              trend={null}
              color="violet"
            />
          </div>

          {/* ---- Tab Navigation ---- */}
          <div className="flex gap-1 rounded-xl bg-white/[.03] p-1">
            <TabButton active={activeTab === "pipeline"} onClick={() => setActiveTab("pipeline")}>
              パイプライン
            </TabButton>
            <TabButton active={activeTab === "logs"} onClick={() => setActiveTab("logs")}>
              ログ
            </TabButton>
            <TabButton active={activeTab === "knowledge"} onClick={() => setActiveTab("knowledge")}>
              {"\u{1F4DA}"} ナレッジ
            </TabButton>
            <TabButton active={activeTab === "feedback"} onClick={() => setActiveTab("feedback")}>
              {"\u{1F9E0}"} フィードバック
            </TabButton>
          </div>

          {/* ---- V2 Command Center Panel ---- */}
          {activeTab === "pipeline" && data.v2 && (
            <section className="mb-4 space-y-3">
              {/* Scoring Warnings */}
              {data.v2.scoringWarnings.length > 0 && (
                <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4">
                  <h3 className="mb-2 text-sm font-bold text-red-400">🚨 方針矛盾チェッカー</h3>
                  {data.v2.scoringWarnings.map((w, i) => (
                    <p key={i} className="text-xs text-red-300">{w}</p>
                  ))}
                </div>
              )}

              {/* Run Summary */}
              {data.v2.latestRunId && (
                <div className="rounded-xl border border-white/[.08] bg-white/[.03] p-4">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-bold text-white/90">🎯 V2 司令塔</h3>
                    <span className="text-[10px] text-white/40 font-mono">run: {data.v2.latestRunId.slice(0, 8)}</span>
                  </div>

                  {/* Gate Results */}
                  <div className="mb-3">
                    <p className="text-xs text-white/50 mb-1">ゲート結果</p>
                    <div className="flex flex-wrap gap-2">
                      {data.v2.gateResults.map((g, i) => (
                        <span
                          key={i}
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                            g.status === "PASS"
                              ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                              : "bg-red-500/10 text-red-400 border border-red-500/20"
                          }`}
                        >
                          {g.status === "PASS" ? "✅" : "❌"} {(g.micro_market || "").slice(0, 25)}
                        </span>
                      ))}
                      {data.v2.gateResults.length === 0 && (
                        <span className="text-[11px] text-white/30">まだ実行されていません</span>
                      )}
                    </div>
                  </div>

                  {/* Offers */}
                  {data.v2.offers.length > 0 && (
                    <div className="mb-3">
                      <p className="text-xs text-white/50 mb-1">オファー3案</p>
                      <div className="space-y-1">
                        {data.v2.offers.map((o, i) => (
                          <div key={i} className="flex items-center gap-2 text-[11px]">
                            <span className="text-white/70">#{o.offer_num}</span>
                            <span className="text-white/90 font-medium">{o.offer_name}</span>
                            <span className="text-white/40">{o.price}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* LP Ready Status */}
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-white/50">LP作成:</span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                        data.v2.lpReadyStatus === "READY"
                          ? "bg-emerald-500/15 text-emerald-400"
                          : data.v2.lpReadyStatus === "BLOCKED"
                            ? "bg-red-500/10 text-red-400"
                            : "bg-white/5 text-white/30"
                      }`}
                    >
                      {data.v2.lpReadyStatus || "未実行"}
                    </span>
                  </div>

                  {/* CEO Review Needed */}
                  {(data.v2.ceoReviewNeeded.market || data.v2.ceoReviewNeeded.offer) && (
                    <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
                      <p className="text-xs font-bold text-amber-400 mb-1">👔 CEO承認が必要です</p>
                      {data.v2.ceoReviewNeeded.market && (
                        <p className="text-[11px] text-amber-300/80">
                          • PASS市場が複数あります。却下して1つに絞ってください。
                        </p>
                      )}
                      {data.v2.ceoReviewNeeded.offer && (
                        <p className="text-[11px] text-amber-300/80">
                          • オファーが複数あります。却下して絞ってください。
                        </p>
                      )}
                    </div>
                  )}
                </div>
              )}
            </section>
          )}

          {/* ---- Downstream Funnel ---- */}
          {activeTab === "pipeline" && data.downstream && data.downstream.totalInquiries > 0 && (
            <section className="rounded-2xl border border-white/[.08] bg-white/[.03] p-5">
              <h3 className="mb-3 text-sm font-bold text-white/90">ファネル</h3>
              <div className="flex items-end gap-2">
                {[
                  { label: "問い合わせ", value: data.downstream.totalInquiries, color: "bg-blue-500" },
                  { label: "適格", value: data.downstream.qualifiedInquiries, color: "bg-cyan-500" },
                  { label: "商談中", value: data.downstream.activeDeals, color: "bg-amber-500" },
                  { label: "成約", value: data.downstream.wonDeals, color: "bg-emerald-500" },
                  { label: "失注", value: data.downstream.lostDeals, color: "bg-red-500" },
                ].map((step) => {
                  const maxVal = Math.max(data.downstream!.totalInquiries, 1);
                  const height = Math.max((step.value / maxVal) * 120, 8);
                  return (
                    <div key={step.label} className="flex flex-1 flex-col items-center gap-1">
                      <span className="text-xs font-semibold text-white/80">{step.value}</span>
                      <div
                        className={`w-full rounded-t-lg ${step.color} transition-all`}
                        style={{ height: `${height}px` }}
                      />
                      <span className="text-[10px] text-white/40">{step.label}</span>
                    </div>
                  );
                })}
              </div>
              {data.downstream.totalDealValue > 0 && (
                <p className="mt-3 text-center text-xs text-white/50">
                  成約金額合計: <span className="font-semibold text-emerald-400">{data.downstream.totalDealValue.toLocaleString()}円</span>
                </p>
              )}
            </section>
          )}

          {/* ---- Expansion Patterns ---- */}
          {activeTab === "pipeline" && data.expansion && data.expansion.totalPatterns > 0 && (
            <section className="rounded-2xl border border-violet-500/20 bg-gradient-to-r from-violet-500/[.04] to-purple-500/[.04] p-5">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-bold text-violet-300">拡張層 — 勝ちパターン</h3>
                <span className="text-[10px] text-white/30">{data.expansion.activePatterns}件アクティブ / {data.expansion.scalingPatterns}件スケーリング中</span>
              </div>
              <div className="space-y-2">
                {data.expansion.patterns.map((p, i) => (
                  <div key={i} className="flex items-center gap-3 rounded-xl bg-black/30 p-3">
                    <span className={`h-2 w-2 rounded-full ${
                      p.status === "scaling" ? "bg-emerald-400 animate-pulse" :
                      p.status === "validated" ? "bg-blue-400" :
                      p.status === "detected" ? "bg-amber-400" :
                      "bg-white/20"
                    }`} />
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-medium text-white/80">{p.micro_market}</p>
                      <p className="text-[10px] text-white/40">{p.offer_name} — {p.payer}</p>
                    </div>
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                      p.pattern_type === "quick_win" ? "bg-emerald-500/15 text-emerald-400" :
                      p.pattern_type === "steady_growth" ? "bg-blue-500/15 text-blue-400" :
                      "bg-violet-500/15 text-violet-400"
                    }`}>
                      {p.pattern_type === "quick_win" ? "即効型" :
                       p.pattern_type === "steady_growth" ? "安定成長" : "高ポテンシャル"}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* ---- Pipeline Status ---- */}
          {activeTab === "pipeline" && (
            <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {data.pipeline.map((script) => {
                const meta = PIPELINE_META[script.id] || { icon: "\u2699\uFE0F", schedule: "", schedulers: [] };
                const badge = STATUS_BADGE[script.status] || STATUS_BADGE.idle;
                const isExecuting = executing === script.id;

                const scriptSchedulers = meta.schedulers;
                const allScriptSchedulersEnabled = scriptSchedulers.every(
                  (name) => schedulerStatus[name]?.state === "ENABLED"
                );
                const isTogglingAny = scriptSchedulers.some(
                  (name) => togglingScheduler === name
                );

                return (
                  <div
                    key={script.id}
                    className="group relative overflow-hidden rounded-2xl border border-white/[.06] bg-white/[.02] p-5 transition-all hover:border-white/[.12] hover:bg-white/[.04]"
                  >
                    {script.status === "running" && (
                      <div className="absolute -top-20 -right-20 h-40 w-40 rounded-full bg-blue-500/10 blur-3xl" />
                    )}

                    <div className="relative flex items-start justify-between">
                      <div className="flex items-center gap-3">
                        <span className="text-xl">{meta.icon}</span>
                        <div>
                          <p className="text-sm font-medium">{script.label}</p>
                          <div className="flex items-center gap-1.5 flex-wrap">
                            {scriptSchedulers.length <= 1 ? (
                              /* Single scheduler — show one line */
                              <>
                                <p className="text-[10px] text-white/30">
                                  {(() => {
                                    const firstScheduler = scriptSchedulers[0];
                                    const realCron = firstScheduler ? schedulerStatus[firstScheduler]?.schedule : "";
                                    return realCron ? cronToJapanese(realCron) : meta.schedule;
                                  })()}
                                </p>
                                {scriptSchedulers.length === 1 && (
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      const name = scriptSchedulers[0];
                                      const currentCron = schedulerStatus[name]?.schedule || "";
                                      setScheduleEditTarget({
                                        schedulerName: name,
                                        scriptLabel: script.label,
                                        currentCron,
                                      });
                                      setScheduleEditCron(currentCron);
                                    }}
                                    className="text-[9px] text-white/20 hover:text-blue-400 transition-colors"
                                    title="スケジュール編集"
                                  >
                                    {"\u270F\uFE0F"}
                                  </button>
                                )}
                              </>
                            ) : (
                              /* Multiple schedulers — show each with its own edit button */
                              <div className="flex flex-col gap-0.5">
                                {scriptSchedulers.map((name) => {
                                  const realCron = schedulerStatus[name]?.schedule || "";
                                  const suffix = SCHEDULER_LABEL[name] || name.replace(/^schedule-/, "");
                                  return (
                                    <div key={name} className="flex items-center gap-1">
                                      <p className="text-[10px] text-white/30">
                                        {suffix}: {realCron ? cronToJapanese(realCron) : "—"}
                                      </p>
                                      <button
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          const currentCron = schedulerStatus[name]?.schedule || "";
                                          setScheduleEditTarget({
                                            schedulerName: name,
                                            scriptLabel: `${script.label}（${suffix}）`,
                                            currentCron,
                                          });
                                          setScheduleEditCron(currentCron);
                                        }}
                                        className="text-[9px] text-white/20 hover:text-blue-400 transition-colors"
                                        title={`${suffix}スケジュール編集`}
                                      >
                                        {"\u270F\uFE0F"}
                                      </button>
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                      <div className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-medium ${badge.bg} ${badge.text}`}>
                        <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT[script.status] || STATUS_DOT.idle}`} />
                        {badge.label}
                      </div>
                    </div>

                    {script.detail && (
                      <p className="relative mt-3 truncate text-xs text-white/40">{script.detail}</p>
                    )}

                    <div className="relative mt-3 flex items-center justify-between text-[10px] text-white/20">
                      <span>{formatTime(script.lastRun)}</span>
                      {script.lastRun && <span>{relativeTime(script.lastRun)}</span>}
                    </div>

                    {Object.keys(script.metrics).length > 0 && (
                      <div className="relative mt-3 flex flex-wrap gap-2 border-t border-white/[.06] pt-3">
                        {Object.entries(script.metrics).map(([k, v]) => (
                          <span key={k} className="rounded-md bg-white/5 px-2 py-0.5 text-[10px] text-white/40">
                            {({
                              // V2 metrics
                              micro_markets_generated: "生成マイクロ市場",
                              a1q_passed: "A1q通過",
                              a1q_failed: "A1q不合格",
                              a1d_passed: "A1dゲート通過",
                              a1d_failed: "A1dゲート不合格",
                              exploration_lanes: "探索レーン",
                              competitors_20: "競合20社分析",
                              gap_top3: "穴トップ3",
                              offers_generated: "即決オファー",
                              lp_ready: "LP作成可",
                              lp_blocked: "LP作成不可",
                              // V1 / shared metrics
                              segments_researched: "調査セグメント",
                              markets_scored: "スコアリング市場",
                              competitors_analyzed: "競合分析",
                              markets_processed: "処理市場",
                              ideas_generated: "生成アイデア",
                              lps_generated: "生成LP",
                              posted: "投稿",
                              reviewed: "レビュー済",
                              blocked: "ブロック",
                              sent: "送信",
                              suggestions: "提案",
                              total_pageviews: "総PV",
                              lps_analyzed: "分析LP",
                              bid_adjustments: "入札調整",
                              kill_flagged: "損切り対象",
                              downstream_inquiries: "問い合わせ",
                              downstream_deals_won: "成約",
                              downstream_deal_rate: "成約率",
                              patterns_detected: "パターン検出",
                              sops_generated: "SOP生成",
                              v2_insights: "V2インサイト",
                            } as Record<string, string>)[k] || k.replace(/_/g, " ")}: <span className="text-white/70 font-medium">{v}</span>
                          </span>
                        ))}
                      </div>
                    )}

                    {/* ---- Action Bar ---- */}
                    <div className="relative mt-4 flex items-center justify-between border-t border-white/[.06] pt-3">
                      <button
                        onClick={() => handleExecute(script.id)}
                        disabled={isExecuting || script.status === "running"}
                        className="flex items-center gap-1.5 rounded-lg bg-blue-600/20 px-3 py-1.5 text-[11px] font-medium text-blue-400 transition-all hover:bg-blue-600/30 disabled:opacity-40 disabled:cursor-not-allowed border border-blue-500/20"
                      >
                        {isExecuting ? (
                          <>
                            <span className="h-3 w-3 animate-spin rounded-full border border-blue-400/30 border-t-blue-400" />
                            {"\u5B9F\u884C\u4E2D..."}
                          </>
                        ) : (
                          <>
                            <span className="text-xs">{"\u25B6"}</span>
                            {"\u5B9F\u884C"}
                          </>
                        )}
                      </button>

                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-white/30">
                          {allScriptSchedulersEnabled ? "\u81EA\u52D5ON" : "\u81EA\u52D5OFF"}
                        </span>
                        <button
                          onClick={() => {
                            for (const name of scriptSchedulers) {
                              handleSchedulerToggle(
                                name,
                                allScriptSchedulersEnabled ? "ENABLED" : "PAUSED"
                              );
                            }
                          }}
                          disabled={isTogglingAny}
                          className={`relative h-5 w-9 rounded-full transition-colors ${
                            allScriptSchedulersEnabled ? "bg-emerald-600" : "bg-white/10"
                          } ${isTogglingAny ? "opacity-50" : ""}`}
                        >
                          <span
                            className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-all ${
                              allScriptSchedulersEnabled ? "left-[18px]" : "left-0.5"
                            }`}
                          />
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </section>
          )}

          {/* ---- Logs ---- */}
          {activeTab === "logs" && (
            <section className="rounded-2xl border border-white/[.06] bg-white/[.02] p-5">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-medium text-white/60">実行ログ</h2>
                <span className="text-[10px] text-white/20">{data.logs.length}件</span>
              </div>
              <div className="max-h-[500px] overflow-y-auto rounded-xl bg-black/50 p-4 font-mono text-[11px] leading-5">
                {data.logs.length === 0 ? (
                  <p className="text-white/20">ログはまだありません</p>
                ) : (
                  data.logs.map((line, i) => (
                    <div
                      key={i}
                      className={`${
                        line.includes("ERROR") || line.includes("AUTO-PAUSE") || line.includes("CRITICAL")
                          ? "text-red-400"
                          : line.includes("WARNING") || line.includes("BLOCKED")
                          ? "text-amber-400"
                          : line.includes("success") || line.includes("complete") || line.includes("\u2705")
                          ? "text-emerald-400"
                          : line.includes("manual") || line.includes("triggered")
                          ? "text-blue-400"
                          : line.includes("INFO")
                          ? "text-white/35"
                          : "text-white/25"
                      }`}
                    >
                      {line}
                    </div>
                  ))
                )}
                <div ref={logEndRef} />
              </div>
            </section>
          )}

          {/* ---- Knowledge Tab ---- */}
          {activeTab === "knowledge" && (
            <div className="space-y-6">
              {/* Upload Area */}
              <section className="rounded-2xl border border-dashed border-violet-500/30 bg-gradient-to-r from-violet-500/[.04] to-purple-500/[.04] p-6">
                <div
                  className="flex flex-col items-center justify-center gap-3 cursor-pointer"
                  onClick={() => fileInputRef.current?.click()}
                  onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
                  onDrop={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const file = e.dataTransfer.files?.[0];
                    const supportedExts = [".pdf", ".csv", ".xlsx", ".xls", ".png", ".jpg", ".jpeg", ".webp"];
                    if (file && supportedExts.some(ext => file.name.toLowerCase().endsWith(ext))) handleFileUpload(file);
                  }}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf,.csv,.xlsx,.xls,.png,.jpg,.jpeg,.webp"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) handleFileUpload(file);
                    }}
                  />
                  {uploading ? (
                    <>
                      <div className="h-8 w-8 animate-spin rounded-full border-2 border-violet-400/30 border-t-violet-400" />
                      <p className="text-sm text-violet-300">{"\u30D5\u30A1\u30A4\u30EB\u3092\u5206\u6790\u4E2D"}...</p>
                      <p className="text-[10px] text-white/30">{"AI\u3067\u30B3\u30F3\u30C6\u30F3\u30C4\u3092\u5206\u6790\u3057\u3066\u3044\u307E\u3059"}</p>
                    </>
                  ) : (
                    <>
                      <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-violet-500/10">
                        <span className="text-2xl">{"\u{1F4CE}"}</span>
                      </div>
                      <p className="text-sm font-medium text-violet-300">{"\u30D5\u30A1\u30A4\u30EB\u3092\u30A2\u30C3\u30D7\u30ED\u30FC\u30C9"}</p>
                      <p className="text-[10px] text-white/30">{"PDF, CSV, Excel, \u753B\u50CF\u306B\u5BFE\u5FDC\uFF08\u6700\u5927 4MB\uFF09"}</p>
                      <p className="text-[9px] text-white/20 mt-1">{"4MB\u4EE5\u4E0A\u306E\u30D5\u30A1\u30A4\u30EB\u306F\u30BF\u30FC\u30DF\u30CA\u30EB\u304B\u3089: python3 scripts/upload_knowledge.py references/\u30D5\u30A1\u30A4\u30EB\u540D"}</p>
                    </>
                  )}
                </div>
              </section>

              {/* Document List */}
              <section>
                <h2 className="mb-3 text-sm font-medium text-white/60">
                  {"\u767B\u9332\u6E08\u307F\u30C9\u30AD\u30E5\u30E1\u30F3\u30C8"} ({knowledgeDocs.length})
                </h2>
                {knowledgeLoading ? (
                  <div className="flex h-20 items-center justify-center">
                    <div className="h-5 w-5 animate-spin rounded-full border-2 border-white/20 border-t-violet-400" />
                  </div>
                ) : knowledgeDocs.length === 0 ? (
                  <div className="rounded-2xl border border-white/[.06] bg-white/[.02] p-8 text-center">
                    <p className="text-sm text-white/30">{"\u307E\u3060\u30C9\u30AD\u30E5\u30E1\u30F3\u30C8\u304C\u767B\u9332\u3055\u308C\u3066\u3044\u307E\u305B\u3093"}</p>
                    <p className="mt-1 text-[10px] text-white/15">{"\u4E0A\u306E\u30A2\u30C3\u30D7\u30ED\u30FC\u30C9\u3067\u30D5\u30A1\u30A4\u30EB\u3092\u8FFD\u52A0\u3057\u3066\u304F\u3060\u3055\u3044"}</p>
                  </div>
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {knowledgeDocs.map((doc) => (
                      <div
                        key={doc.id}
                        className="rounded-2xl border border-white/[.06] bg-white/[.02] p-5 transition-all hover:border-white/[.12]"
                      >
                        <div className="flex items-start gap-3">
                          <span className="text-2xl">{"\u{1F4D6}"}</span>
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-medium">{doc.title}</p>
                            <p className="mt-1 text-xs text-white/40 line-clamp-3">{doc.summary}</p>
                            <div className="mt-3 flex flex-wrap gap-1.5">
                              <span className="rounded-md bg-violet-500/10 px-2 py-0.5 text-[10px] text-violet-400 border border-violet-500/20">
                                {doc.chapterCount} {"\u7AE0"}
                              </span>
                              {doc.keyFrameworks.slice(0, 3).map((fw) => (
                                <span key={fw} className="rounded-md bg-white/5 px-2 py-0.5 text-[10px] text-white/40">
                                  {fw}
                                </span>
                              ))}
                            </div>
                            <p className="mt-2 text-[10px] text-white/20">{formatTime(doc.uploadedAt)}</p>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              {/* Chat UI */}
              <section className="rounded-2xl border border-white/[.06] bg-white/[.02] p-5">
                <div className="mb-3 flex items-center gap-2">
                  <span className="text-lg">{"\u{1F4AC}"}</span>
                  <h2 className="text-sm font-medium text-white/60">{"\u77E5\u8B58\u30D9\u30FC\u30B9 Q&A"}</h2>
                </div>

                {/* Messages */}
                <div className="mb-4 max-h-[400px] overflow-y-auto rounded-xl bg-black/30 p-4 space-y-4">
                  {chatMessages.length === 0 ? (
                    <div className="text-center py-8">
                      <p className="text-sm text-white/20">{"\u66F8\u7C4D\u306E\u5185\u5BB9\u306B\u3064\u3044\u3066\u8CEA\u554F\u3057\u3066\u307F\u307E\u3057\u3087\u3046"}</p>
                      <div className="mt-4 flex flex-wrap justify-center gap-2">
                        {["\u4E8B\u696D\u691C\u8A3C\u306E\u30D5\u30EC\u30FC\u30E0\u30EF\u30FC\u30AF\u306F\uFF1F", "MIT 24\u30B9\u30C6\u30C3\u30D7\u306E\u6982\u8981\u306F\uFF1F", "TAM\u306E\u7B97\u51FA\u65B9\u6CD5\u306F\uFF1F"].map((q) => (
                          <button
                            key={q}
                            onClick={() => { setChatInput(q); }}
                            className="rounded-lg bg-white/5 px-3 py-1.5 text-[11px] text-white/40 hover:bg-white/10 hover:text-white/60 transition-colors"
                          >
                            {q}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : (
                    chatMessages.map((msg, i) => (
                      <div
                        key={i}
                        className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                      >
                        <div
                          className={`max-w-[85%] rounded-xl px-4 py-2.5 text-xs leading-relaxed ${
                            msg.role === "user"
                              ? "bg-blue-600/20 text-blue-200 border border-blue-500/20"
                              : "bg-white/5 text-white/70 border border-white/[.06]"
                          }`}
                        >
                          <div className="whitespace-pre-wrap">{msg.content}</div>
                        </div>
                      </div>
                    ))
                  )}
                  {chatLoading && chatMessages[chatMessages.length - 1]?.content === "" && (
                    <div className="flex justify-start">
                      <div className="rounded-xl bg-white/5 px-4 py-2.5 border border-white/[.06]">
                        <div className="flex gap-1">
                          <span className="h-1.5 w-1.5 rounded-full bg-white/30 animate-bounce" />
                          <span className="h-1.5 w-1.5 rounded-full bg-white/30 animate-bounce [animation-delay:150ms]" />
                          <span className="h-1.5 w-1.5 rounded-full bg-white/30 animate-bounce [animation-delay:300ms]" />
                        </div>
                      </div>
                    </div>
                  )}
                  <div ref={chatEndRef} />
                </div>

                {/* Input */}
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        handleChatSend();
                      }
                    }}
                    placeholder={"\u66F8\u7C4D\u306E\u5185\u5BB9\u306B\u3064\u3044\u3066\u8CEA\u554F..."}
                    className="flex-1 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-xs text-white outline-none focus:border-violet-500/50 placeholder:text-white/20 transition-colors"
                    disabled={chatLoading}
                  />
                  <button
                    onClick={handleChatSend}
                    disabled={chatLoading || !chatInput.trim()}
                    className="shrink-0 rounded-xl bg-violet-600 px-4 py-2.5 text-xs font-medium text-white transition-all hover:bg-violet-500 disabled:opacity-40"
                  >
                    {chatLoading ? "..." : "\u9001\u4FE1"}
                  </button>
                </div>
              </section>
            </div>
          )}

          {/* ---- Feedback Tab ---- */}
          {activeTab === "feedback" && (
            <div className="space-y-6">
              {/* Performance Summary Cards */}
              {feedbackPerf.length > 0 && (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {feedbackPerf.map((p) => (
                    <div key={p.businessId} className="rounded-2xl border border-amber-500/10 bg-gradient-to-br from-amber-500/[.06] to-orange-500/[.03] p-4">
                      <p className="text-xs font-medium text-amber-300">{p.businessId}</p>
                      <div className="mt-2 flex items-baseline gap-2">
                        <span className="text-2xl font-semibold">{p.latestScore}</span>
                        <span className="text-[10px] text-white/30">/100 ({"\u5E73\u5747"}{p.avgScore})</span>
                      </div>
                      <div className="mt-2 flex gap-3 text-[10px] text-white/40">
                        <span>PV {p.latestPV}</span>
                        <span>CVR {p.latestCVR}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Learning Memories */}
              <section className="rounded-2xl border border-white/[.06] bg-white/[.02] p-5">
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-lg">{"\u{1F4DD}"}</span>
                    <h2 className="text-sm font-medium text-white/60">{"\u5B66\u7FD2\u30E1\u30E2\u30EA"} ({feedbackMemories.length})</h2>
                  </div>
                </div>
                {feedbackMemories.length === 0 ? (
                  <p className="text-center py-4 text-sm text-white/20">{"\u307E\u3060\u5B66\u7FD2\u30E1\u30E2\u30EA\u304C\u3042\u308A\u307E\u305B\u3093"}</p>
                ) : (
                  <div className="space-y-2 max-h-[300px] overflow-y-auto">
                    {feedbackMemories.map((m) => (
                      <div key={m.id} className="flex items-start gap-3 rounded-xl bg-black/30 p-3">
                        <span className="mt-0.5 text-sm">
                          {m.source === "human_chat" ? "\u{1F464}" : "\u{1F916}"}
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="text-xs text-white/70">{m.content}</p>
                          <div className="mt-1.5 flex flex-wrap gap-1.5">
                            <span className={`rounded-md px-1.5 py-0.5 text-[9px] border ${
                              m.type === "directive"
                                ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
                                : m.type === "pattern"
                                ? "bg-violet-500/10 text-violet-400 border-violet-500/20"
                                : "bg-blue-500/10 text-blue-400 border-blue-500/20"
                            }`}>
                              {m.type}
                            </span>
                            <span className="rounded-md bg-white/5 px-1.5 py-0.5 text-[9px] text-white/40">{m.category}</span>
                            <span className={`rounded-md px-1.5 py-0.5 text-[9px] ${
                              m.priority === "high" ? "bg-red-500/10 text-red-400" :
                              m.priority === "medium" ? "bg-yellow-500/10 text-yellow-400" :
                              "bg-white/5 text-white/30"
                            }`}>
                              {m.priority}
                            </span>
                          </div>
                        </div>
                        <button
                          onClick={() => handleSupersede(m.id)}
                          className="shrink-0 rounded-lg bg-white/5 px-2 py-1 text-[10px] text-white/30 hover:bg-red-500/10 hover:text-red-400 transition-colors"
                          title={"\u7121\u52B9\u5316"}
                        >
                          {"\u2716"}
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              {/* Feedback Chat UI */}
              <section className="rounded-2xl border border-amber-500/10 bg-white/[.02] p-5">
                <div className="mb-3 flex items-center gap-2">
                  <span className="text-lg">{"\u{1F4AC}"}</span>
                  <h2 className="text-sm font-medium text-amber-300">{"\u904B\u7528\u30D5\u30A3\u30FC\u30C9\u30D0\u30C3\u30AF"}</h2>
                </div>

                {/* Messages */}
                <div className="mb-4 max-h-[400px] overflow-y-auto rounded-xl bg-black/30 p-4 space-y-4">
                  {feedbackMessages.length === 0 ? (
                    <div className="text-center py-8">
                      <p className="text-sm text-white/20">{"\u30D1\u30D5\u30A9\u30FC\u30DE\u30F3\u30B9\u306B\u3064\u3044\u3066\u8CEA\u554F\u3057\u305F\u308A\u3001\u65B9\u91DD\u3092\u6307\u793A\u3057\u305F\u308A"}</p>
                      <div className="mt-4 flex flex-wrap justify-center gap-2">
                        {[
                          "\u76F4\u8FD1\u306ELP\u6210\u679C\u3092\u6559\u3048\u3066",
                          "SNS\u306F\u30AB\u30B8\u30E5\u30A2\u30EB\u306A\u30C8\u30FC\u30F3\u3067",
                          "\u30D5\u30A9\u30FC\u30E0\u55B6\u696D\u306E\u6539\u5584\u70B9\u306F\uFF1F",
                          "\u4ECA\u5F8C\u306E\u6226\u7565\u3092\u63D0\u6848\u3057\u3066",
                        ].map((q) => (
                          <button
                            key={q}
                            onClick={() => setFeedbackInput(q)}
                            className="rounded-lg bg-amber-500/5 px-3 py-1.5 text-[11px] text-amber-400/60 hover:bg-amber-500/10 hover:text-amber-400 transition-colors border border-amber-500/10"
                          >
                            {q}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : (
                    feedbackMessages.map((msg, i) => (
                      <div
                        key={i}
                        className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                      >
                        <div
                          className={`max-w-[85%] rounded-xl px-4 py-2.5 text-xs leading-relaxed ${
                            msg.role === "user"
                              ? "bg-amber-600/20 text-amber-200 border border-amber-500/20"
                              : "bg-white/5 text-white/70 border border-white/[.06]"
                          }`}
                        >
                          <div className="whitespace-pre-wrap">{msg.content}</div>
                        </div>
                      </div>
                    ))
                  )}
                  {feedbackLoading && feedbackMessages[feedbackMessages.length - 1]?.content === "" && (
                    <div className="flex justify-start">
                      <div className="rounded-xl bg-white/5 px-4 py-2.5 border border-white/[.06]">
                        <div className="flex gap-1">
                          <span className="h-1.5 w-1.5 rounded-full bg-amber-400/30 animate-bounce" />
                          <span className="h-1.5 w-1.5 rounded-full bg-amber-400/30 animate-bounce [animation-delay:150ms]" />
                          <span className="h-1.5 w-1.5 rounded-full bg-amber-400/30 animate-bounce [animation-delay:300ms]" />
                        </div>
                      </div>
                    </div>
                  )}
                  <div ref={feedbackEndRef} />
                </div>

                {/* Input */}
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={feedbackInput}
                    onChange={(e) => setFeedbackInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        handleFeedbackSend();
                      }
                    }}
                    placeholder={"\u30D1\u30D5\u30A9\u30FC\u30DE\u30F3\u30B9\u306B\u3064\u3044\u3066\u8CEA\u554F\u3001\u307E\u305F\u306F\u65B9\u91DD\u3092\u6307\u793A..."}
                    className="flex-1 rounded-xl border border-amber-500/20 bg-white/5 px-4 py-2.5 text-xs text-white outline-none focus:border-amber-500/50 placeholder:text-white/20 transition-colors"
                    disabled={feedbackLoading}
                  />
                  <button
                    onClick={handleFeedbackSend}
                    disabled={feedbackLoading || !feedbackInput.trim()}
                    className="shrink-0 rounded-xl bg-amber-600 px-4 py-2.5 text-xs font-medium text-white transition-all hover:bg-amber-500 disabled:opacity-40"
                  >
                    {feedbackLoading ? "..." : "\u9001\u4FE1"}
                  </button>
                </div>
              </section>
            </div>
          )}

          {/* ---- Schedule Edit Modal ---- */}
          {scheduleEditTarget && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
              <div className="w-full max-w-md rounded-2xl border border-white/10 bg-[#12121a] p-6 shadow-2xl">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-white">
                    スケジュール編集 — {scheduleEditTarget.scriptLabel}
                  </h3>
                  <button
                    onClick={() => setScheduleEditTarget(null)}
                    className="text-white/30 hover:text-white/60 text-lg"
                  >
                    {"\u2715"}
                  </button>
                </div>

                <div className="mb-4">
                  <p className="mb-1 text-[10px] text-white/30">現在のスケジュール</p>
                  <p className="text-xs text-white/60">
                    {scheduleEditTarget.currentCron
                      ? `${cronToJapanese(scheduleEditTarget.currentCron)} (${scheduleEditTarget.currentCron})`
                      : "未設定"}
                  </p>
                </div>

                <div className="mb-4">
                  <p className="mb-2 text-[10px] text-white/30">プリセット</p>
                  <div className="flex flex-wrap gap-2">
                    {SCHEDULE_PRESETS.map((preset) => (
                      <button
                        key={preset.cron}
                        onClick={() => setScheduleEditCron(preset.cron)}
                        className={`rounded-lg px-3 py-1.5 text-[11px] border transition-all ${
                          scheduleEditCron === preset.cron
                            ? "bg-blue-600/20 text-blue-400 border-blue-500/30"
                            : "bg-white/5 text-white/40 border-white/10 hover:bg-white/10"
                        }`}
                      >
                        {preset.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="mb-5">
                  <p className="mb-1 text-[10px] text-white/30">カスタムcron式 (分 時 日 月 曜日)</p>
                  <input
                    type="text"
                    value={scheduleEditCron}
                    onChange={(e) => setScheduleEditCron(e.target.value)}
                    placeholder="0 9 * * *"
                    className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-xs text-white font-mono outline-none focus:border-blue-500/50 placeholder:text-white/20"
                  />
                  {scheduleEditCron && (
                    <p className="mt-1 text-[10px] text-blue-400/60">
                      {cronToJapanese(scheduleEditCron)}
                    </p>
                  )}
                </div>

                <div className="flex gap-3">
                  <button
                    onClick={() => setScheduleEditTarget(null)}
                    className="flex-1 rounded-xl bg-white/5 py-2.5 text-xs font-medium text-white/60 hover:bg-white/10 transition-colors"
                  >
                    キャンセル
                  </button>
                  <button
                    onClick={handleScheduleSave}
                    disabled={scheduleEditSaving || !scheduleEditCron.trim()}
                    className="flex-1 rounded-xl bg-blue-600 py-2.5 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-40 transition-colors"
                  >
                    {scheduleEditSaving ? "保存中..." : "保存"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* ---- System Health Bar + Global Controls ---- */}
          <footer className="flex flex-col gap-3 rounded-2xl border border-white/[.06] bg-white/[.02] px-5 py-3">
            <div className="flex items-center justify-between text-[11px] text-white/30">
              <div className="flex items-center gap-4">
                <span className="flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                  {successCount}/{data.pipeline.length} 正常
                </span>
                <span>|</span>
                <span>{enabledSchedulers}/{allSchedulerNames.length} スケジューラー稼働中</span>
              </div>
              <div className="flex items-center gap-4">
                <span>自動更新: {autoRefresh ? "ON" : "OFF"}</span>
                <span>|</span>
                <span>{formatTime(data.lastUpdated)}</span>
              </div>
            </div>

            <div className="flex items-center justify-center gap-3 border-t border-white/[.06] pt-3">
              <button
                onClick={() => handleGlobalToggle("resume_all")}
                disabled={globalToggling || allEnabled}
                className="flex items-center gap-1.5 rounded-lg bg-emerald-600/20 px-4 py-2 text-xs font-medium text-emerald-400 transition-all hover:bg-emerald-600/30 disabled:opacity-30 disabled:cursor-not-allowed border border-emerald-500/20"
              >
                {globalToggling ? (
                  <span className="h-3 w-3 animate-spin rounded-full border border-emerald-400/30 border-t-emerald-400" />
                ) : (
                  <span>{"\u25B6"}</span>
                )}
                {"\u5168\u4F53\u30B9\u30BF\u30FC\u30C8"}
              </button>
              <button
                onClick={() => handleGlobalToggle("pause_all")}
                disabled={globalToggling || allPaused}
                className="flex items-center gap-1.5 rounded-lg bg-red-600/20 px-4 py-2 text-xs font-medium text-red-400 transition-all hover:bg-red-600/30 disabled:opacity-30 disabled:cursor-not-allowed border border-red-500/20"
              >
                {globalToggling ? (
                  <span className="h-3 w-3 animate-spin rounded-full border border-red-400/30 border-t-red-400" />
                ) : (
                  <span>{"\u23F8"}</span>
                )}
                {"\u5168\u4F53\u30B9\u30C8\u30C3\u30D7"}
              </button>
            </div>
          </footer>
        </main>
    </AppShell>
  );
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
/* ------------------------------------------------------------------ */
function KPICard({
  label,
  value,
  trend,
  color,
}: {
  label: string;
  value: number | string;
  trend: number | null;
  color: "blue" | "violet" | "emerald" | "orange" | "pink";
}) {
  const gradients: Record<string, string> = {
    blue: "from-blue-500/10 to-blue-600/5 border-blue-500/10",
    violet: "from-violet-500/10 to-violet-600/5 border-violet-500/10",
    emerald: "from-emerald-500/10 to-emerald-600/5 border-emerald-500/10",
    orange: "from-orange-500/10 to-orange-600/5 border-orange-500/10",
    pink: "from-pink-500/10 to-pink-600/5 border-pink-500/10",
  };

  const dotColors: Record<string, string> = {
    blue: "bg-blue-500",
    violet: "bg-violet-500",
    emerald: "bg-emerald-500",
    orange: "bg-orange-500",
    pink: "bg-pink-500",
  };

  return (
    <div className={`relative overflow-hidden rounded-2xl border bg-gradient-to-br p-4 ${gradients[color]}`}>
      <div className="flex items-center gap-1.5">
        <span className={`h-1.5 w-1.5 rounded-full ${dotColors[color]}`} />
        <span className="text-[11px] text-white/40 tracking-wide">{label}</span>
      </div>
      <p className="mt-2 text-2xl font-semibold tracking-tight">{value}</p>
      {trend !== null && (
        <p className={`mt-1 text-[10px] ${trend >= 0 ? "text-emerald-400" : "text-red-400"}`}>
          {trend >= 0 ? "\u2191" : "\u2193"} {Math.abs(trend)}% 先週比
        </p>
      )}
    </div>
  );
}

function TabButton({
  children,
  active,
  onClick,
}: {
  children: React.ReactNode;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 rounded-lg px-4 py-2 text-xs font-medium transition-all ${
        active
          ? "bg-white/[.08] text-white shadow-sm"
          : "text-white/40 hover:text-white/60"
      }`}
    >
      {children}
    </button>
  );
}
