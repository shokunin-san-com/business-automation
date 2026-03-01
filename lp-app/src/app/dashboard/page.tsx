"use client";

import { useState } from "react";
import AppShell from "../../components/AppShell";
import { useDashboardData } from "./_hooks/useDashboardData";
import { KPICards } from "./_components/KPICards";
import { ActiveBusinesses } from "./_components/ActiveBusinesses";
import { V2CommandCenter } from "./_components/V2CommandCenter";
import { PipelineCards, PIPELINE_META, formatTime, relativeTime } from "./_components/PipelineCards";
import { LogsTab } from "./_components/LogsTab";
import { KnowledgeTab } from "./_components/KnowledgeTab";
import { FeedbackTab } from "./_components/FeedbackTab";
import { ScheduleEditModal } from "./_components/ScheduleEditModal";
import { ErrorBanner } from "./_components/ErrorBanner";

type Tab = "pipeline" | "logs" | "knowledge" | "feedback";

export default function DashboardPage() {
  const dashboard = useDashboardData();
  const [activeTab, setActiveTab] = useState<Tab>("pipeline");

  if (!dashboard.data) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#0a0a0f]">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-blue-500" />
          <p className="text-sm text-white/40 tracking-wide">ダッシュボードを読み込み中...</p>
        </div>
      </div>
    );
  }

  const { data } = dashboard;
  const runningCount = data.pipeline.filter((s) => s.status === "running").length;
  const errorCount = data.pipeline.filter((s) => s.status === "error").length;
  const successCount = data.pipeline.filter((s) => s.status === "success").length;
  const pendingIdeas = data.pendingIdeas || [];
  const schedulerStatus = data.schedulerStatus || {};

  const allSchedulerNames = Object.values(PIPELINE_META).flatMap((m) => m.schedulers);
  const enabledSchedulers = allSchedulerNames.filter(
    (name) => schedulerStatus[name]?.state === "ENABLED",
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
            onClick={() => dashboard.setAutoRefresh(!dashboard.autoRefresh)}
            className={`relative h-6 w-10 rounded-full transition-colors ${
              dashboard.autoRefresh ? "bg-blue-600" : "bg-white/10"
            }`}
          >
            <span
              className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform ${
                dashboard.autoRefresh ? "translate-x-[18px]" : "translate-x-0.5"
              }`}
            />
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-6 p-6">
        <ErrorBanner errors={data.fetchErrors} />

        <KPICards data={data} />

        {/* Tab Navigation */}
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

        {activeTab === "pipeline" && (
          <>
            <V2CommandCenter
              v2={data.v2}
              pendingIdeas={pendingIdeas}
              approving={dashboard.approving}
              onApprove={dashboard.handleApprove}
            />
            <ActiveBusinesses businesses={data.activeBusinesses} />
            <PipelineCards
              pipeline={data.pipeline}
              schedulerStatus={schedulerStatus}
              executing={dashboard.executing}
              onExecute={dashboard.handleExecute}
              onSchedulerToggle={dashboard.handleSchedulerToggle}
              togglingScheduler={dashboard.togglingScheduler}
              onScheduleEdit={(target) => {
                dashboard.setScheduleEditTarget(target);
                dashboard.setScheduleEditCron(target.currentCron);
              }}
            />
          </>
        )}

        {activeTab === "logs" && <LogsTab logs={data.logs} />}
        {activeTab === "knowledge" && <KnowledgeTab />}
        {activeTab === "feedback" && <FeedbackTab />}

        <ScheduleEditModal
          target={dashboard.scheduleEditTarget}
          cron={dashboard.scheduleEditCron}
          setCron={dashboard.setScheduleEditCron}
          saving={dashboard.scheduleEditSaving}
          onSave={dashboard.handleScheduleSave}
          onClose={() => dashboard.setScheduleEditTarget(null)}
        />

        {/* System Health Bar + Global Controls */}
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
              <span>自動更新: {dashboard.autoRefresh ? "ON" : "OFF"}</span>
              <span>|</span>
              <span>{formatTime(data.lastUpdated)}</span>
            </div>
          </div>

          <div className="flex items-center justify-center gap-3 border-t border-white/[.06] pt-3">
            <button
              onClick={() => dashboard.handleGlobalToggle("resume_all")}
              disabled={dashboard.globalToggling || allEnabled}
              className="flex items-center gap-1.5 rounded-lg bg-emerald-600/20 px-4 py-2 text-xs font-medium text-emerald-400 transition-all hover:bg-emerald-600/30 disabled:opacity-30 disabled:cursor-not-allowed border border-emerald-500/20"
            >
              {dashboard.globalToggling ? (
                <span className="h-3 w-3 animate-spin rounded-full border border-emerald-400/30 border-t-emerald-400" />
              ) : (
                <span>{"\u25B6"}</span>
              )}
              全体スタート
            </button>
            <button
              onClick={() => dashboard.handleGlobalToggle("pause_all")}
              disabled={dashboard.globalToggling || allPaused}
              className="flex items-center gap-1.5 rounded-lg bg-red-600/20 px-4 py-2 text-xs font-medium text-red-400 transition-all hover:bg-red-600/30 disabled:opacity-30 disabled:cursor-not-allowed border border-red-500/20"
            >
              {dashboard.globalToggling ? (
                <span className="h-3 w-3 animate-spin rounded-full border border-red-400/30 border-t-red-400" />
              ) : (
                <span>{"\u23F8"}</span>
              )}
              全体ストップ
            </button>
          </div>
        </footer>
      </main>
    </AppShell>
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
