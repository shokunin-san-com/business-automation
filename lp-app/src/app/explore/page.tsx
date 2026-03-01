"use client";

import { useState, useEffect, useCallback } from "react";
import AppShell from "@/components/AppShell";

interface PipelineRun {
  run_id: string;
  timestamp: string;
  steps: {
    name: string;
    status: string;
    count: number;
    errors: string[];
  }[];
  filterStats: {
    layer1_generated: number;
    layer1_passed: number;
    layer2_generated: number;
    layer2_passed: number;
  };
}

const STEP_STATUS_ICONS: Record<string, string> = {
  OK: "\u2705",
  FAIL: "\u274C",
  SKIP: "\u23ED",
  running: "\u{1F504}",
};

export default function ExplorePage() {
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedRun, setExpandedRun] = useState<string | null>(null);

  const fetchRuns = useCallback(async () => {
    try {
      const res = await fetch("/api/explore");
      if (res.ok) {
        const data = await res.json();
        setRuns(data.runs || []);
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { fetchRuns(); }, [fetchRuns]);

  return (
    <AppShell>
      <main className="mx-auto max-w-4xl space-y-6 p-6">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-bold">パイプライン探索</h1>
          <button
            onClick={fetchRuns}
            className="rounded-lg bg-white/5 px-3 py-1.5 text-xs text-white/50 hover:bg-white/10 transition-colors"
          >
            更新
          </button>
        </div>

        {loading && (
          <div className="flex justify-center py-20">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-blue-500" />
          </div>
        )}

        {!loading && runs.length === 0 && (
          <div className="rounded-2xl border border-white/[.06] bg-white/[.02] p-10 text-center">
            <p className="text-sm text-white/30">パイプライン実行履歴はありません</p>
            <p className="mt-1 text-[10px] text-white/20">
              V3パイプラインを実行すると、各ステップの進捗がここに表示されます
            </p>
          </div>
        )}

        {!loading && runs.map((run) => {
          const isExpanded = expandedRun === run.run_id;
          return (
            <div key={run.run_id} className="rounded-2xl border border-white/[.08] bg-white/[.03] p-5">
              <button
                onClick={() => setExpandedRun(isExpanded ? null : run.run_id)}
                className="flex w-full items-center justify-between text-left"
              >
                <div>
                  <p className="text-sm font-semibold text-white/90 font-mono">
                    run: {run.run_id.slice(0, 8)}
                  </p>
                  <p className="text-[10px] text-white/40 mt-0.5">{run.timestamp}</p>
                </div>
                <span className="text-white/30 text-xs">{isExpanded ? "\u25B2" : "\u25BC"}</span>
              </button>

              {/* Filter Stats Summary */}
              {run.filterStats && (
                <div className="mt-3 grid grid-cols-4 gap-2">
                  <div className="rounded-lg bg-white/[.03] p-2 text-center">
                    <p className="text-sm font-bold text-white/70">{run.filterStats.layer1_generated}</p>
                    <p className="text-[8px] text-white/30">L1 生成</p>
                  </div>
                  <div className="rounded-lg bg-emerald-500/5 p-2 text-center">
                    <p className="text-sm font-bold text-emerald-400">{run.filterStats.layer1_passed}</p>
                    <p className="text-[8px] text-white/30">L1 通過</p>
                  </div>
                  <div className="rounded-lg bg-white/[.03] p-2 text-center">
                    <p className="text-sm font-bold text-white/70">{run.filterStats.layer2_generated}</p>
                    <p className="text-[8px] text-white/30">L2 生成</p>
                  </div>
                  <div className="rounded-lg bg-emerald-500/5 p-2 text-center">
                    <p className="text-sm font-bold text-emerald-400">{run.filterStats.layer2_passed}</p>
                    <p className="text-[8px] text-white/30">L2 通過</p>
                  </div>
                </div>
              )}

              {isExpanded && run.steps && (
                <div className="mt-4 space-y-2 border-t border-white/[.06] pt-4">
                  {run.steps.map((step, i) => (
                    <div key={i}>
                      <div className="flex items-center gap-3 text-[11px]">
                        <span>{STEP_STATUS_ICONS[step.status] || "\u2B55"}</span>
                        <span className="text-white/70 font-medium w-40">{step.name}</span>
                        <span className="text-white/40">{step.count > 0 ? `${step.count}件` : ""}</span>
                        {step.errors.length > 0 && (
                          <span className="rounded-full bg-red-500/10 px-2 py-0.5 text-[10px] text-red-400 border border-red-500/20">
                            {step.errors.length}件エラー
                          </span>
                        )}
                      </div>
                      {step.errors.length > 0 && (
                        <div className="ml-8 mt-1 space-y-1">
                          {step.errors.map((err, j) => (
                            <p key={j} className="text-[10px] text-red-400/80 pl-2 border-l border-red-500/20">
                              {err}
                            </p>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </main>
    </AppShell>
  );
}
