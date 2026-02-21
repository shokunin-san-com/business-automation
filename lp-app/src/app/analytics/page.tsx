"use client";

import { useEffect, useState, useCallback } from "react";
import AppShell from "../../components/AppShell";

interface AnalyticsEntry {
  business_id: string;
  date: string;
  pageviews: number;
  sessions: number;
  bounce_rate: number;
  conversions: number;
  avg_time: number;
}

interface Suggestion {
  business_id: string;
  text: string;
  priority: string;
  date: string;
}

interface AnalyticsData {
  entries: AnalyticsEntry[];
  suggestions: Suggestion[];
  summary: {
    totalPageviews: number;
    totalSessions: number;
    totalConversions: number;
    avgBounceRate: number;
  };
}

export default function AnalyticsPage() {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  // Track which suggestions have been acted on: key = suggestion text
  const [actionedSuggestions, setActionedSuggestions] = useState<Record<string, "accepted" | "dismissed">>({});
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/analytics")
      .then((r) => r.json())
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleSuggestionAction = useCallback(async (suggestion: Suggestion, action: "accept" | "dismiss") => {
    setActionLoading(suggestion.text);
    try {
      const res = await fetch("/api/analytics/suggestions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: suggestion.text,
          priority: suggestion.priority,
          business_id: suggestion.business_id,
          action,
        }),
      });
      if (res.ok) {
        setActionedSuggestions((prev) => ({
          ...prev,
          [suggestion.text]: action === "accept" ? "accepted" : "dismissed",
        }));
      }
    } catch {
      // silently fail
    } finally {
      setActionLoading(null);
    }
  }, []);

  return (
    <AppShell>
      <header className="sticky top-0 z-30 hidden lg:flex h-14 items-center border-b border-white/[.06] bg-[#0a0a0f]/80 px-6 backdrop-blur-xl">
        <h1 className="text-sm font-medium text-white/60">Analytics</h1>
      </header>

      <main className="mx-auto max-w-6xl space-y-6 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">アナリティクス概要</h2>
            <p className="mt-0.5 text-xs text-white/40">分析パイプラインが収集したGA4データ・AI改善提案</p>
          </div>
        </div>

        {loading ? (
          <div className="flex h-40 items-center justify-center">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-blue-500" />
          </div>
        ) : !data || (data.entries.length === 0 && data.suggestions.length === 0) ? (
          <EmptyState />
        ) : (
          <>
            {/* Summary Cards */}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatCard label="ページビュー" value={data.summary.totalPageviews.toLocaleString()} color="blue" />
              <StatCard label="セッション" value={data.summary.totalSessions.toLocaleString()} color="violet" />
              <StatCard label="コンバージョン" value={data.summary.totalConversions.toLocaleString()} color="emerald" />
              <StatCard label="直帰率" value={`${data.summary.avgBounceRate.toFixed(1)}%`} color="orange" />
            </div>

            {/* Data Table */}
            {data.entries.length > 0 && (
            <section className="rounded-2xl border border-white/[.06] bg-white/[.02] p-5 overflow-x-auto">
              <h3 className="mb-4 text-sm font-medium text-white/60">日次メトリクス</h3>
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-white/[.06] text-left text-white/30">
                    <th className="pb-2 pr-4 font-medium">日付</th>
                    <th className="pb-2 pr-4 font-medium">事業</th>
                    <th className="pb-2 pr-4 font-medium text-right">PV</th>
                    <th className="pb-2 pr-4 font-medium text-right">セッション</th>
                    <th className="pb-2 pr-4 font-medium text-right">CV</th>
                    <th className="pb-2 font-medium text-right">直帰率</th>
                  </tr>
                </thead>
                <tbody>
                  {data.entries.slice(0, 30).map((e, i) => (
                    <tr key={i} className="border-b border-white/[.03] text-white/60 hover:bg-white/[.02]">
                      <td className="py-2 pr-4">{e.date}</td>
                      <td className="py-2 pr-4 text-white/80 font-medium">{e.business_id}</td>
                      <td className="py-2 pr-4 text-right">{e.pageviews}</td>
                      <td className="py-2 pr-4 text-right">{e.sessions}</td>
                      <td className="py-2 pr-4 text-right">{e.conversions}</td>
                      <td className="py-2 text-right">{e.bounce_rate}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
            )}

            {data.entries.length === 0 && (
              <div className="rounded-2xl border border-amber-500/10 bg-amber-500/[.03] p-4">
                <p className="text-xs text-amber-400/70">GA4のアクセスデータはまだありません。分析パイプライン実行後に表示されます。</p>
              </div>
            )}

            {/* Improvement Suggestions */}
            {data.suggestions.length > 0 && (
              <section className="rounded-2xl border border-white/[.06] bg-white/[.02] p-5">
                <h3 className="mb-4 text-sm font-medium text-white/60">AI改善提案</h3>
                <div className="space-y-2">
                  {data.suggestions.map((s, i) => {
                    const status = actionedSuggestions[s.text];
                    const isLoading = actionLoading === s.text;

                    return (
                      <div key={i} className={`rounded-xl bg-black/30 p-4 transition-all ${
                        status ? "opacity-60" : ""
                      }`}>
                        <div className="flex items-start gap-3">
                          <span className={`mt-0.5 shrink-0 rounded-md px-2 py-0.5 text-[10px] font-medium ${
                            s.priority === "high" ? "bg-red-500/15 text-red-400" :
                            s.priority === "medium" ? "bg-amber-500/15 text-amber-400" :
                            "bg-blue-500/15 text-blue-400"
                          }`}>
                            {s.priority === "high" ? "高" : s.priority === "medium" ? "中" : "低"}
                          </span>
                          <div className="min-w-0 flex-1">
                            <p className="text-xs text-white/70">{s.text}</p>
                            <p className="mt-1 text-[10px] text-white/30">{s.business_id} {"\u2022"} {s.date}</p>
                          </div>
                        </div>

                        {/* Action buttons or status */}
                        <div className="mt-3 flex items-center gap-2 pl-7">
                          {status === "accepted" ? (
                            <span className="flex items-center gap-1 text-[11px] text-emerald-400/80">
                              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                              </svg>
                              学習メモリに反映済み
                            </span>
                          ) : status === "dismissed" ? (
                            <span className="text-[11px] text-white/30">却下済み</span>
                          ) : (
                            <>
                              <button
                                onClick={() => handleSuggestionAction(s, "accept")}
                                disabled={isLoading}
                                className="flex items-center gap-1 rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-1.5 text-[11px] font-medium text-emerald-400 transition-colors hover:bg-emerald-500/20 disabled:opacity-40"
                              >
                                {isLoading ? (
                                  <span className="h-3 w-3 animate-spin rounded-full border border-emerald-400/30 border-t-emerald-400" />
                                ) : (
                                  <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                                  </svg>
                                )}
                                反映する
                              </button>
                              <button
                                onClick={() => handleSuggestionAction(s, "dismiss")}
                                disabled={isLoading}
                                className="rounded-lg border border-white/[.06] px-3 py-1.5 text-[11px] text-white/30 transition-colors hover:bg-white/[.04] hover:text-white/50 disabled:opacity-40"
                              >
                                却下
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            )}
          </>
        )}
      </main>
    </AppShell>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-white/[.06] bg-white/[.02] py-20">
      <svg className="h-12 w-12 text-white/10" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
      </svg>
      <p className="mt-4 text-sm text-white/30">アナリティクスデータがありません</p>
      <p className="mt-1 text-[11px] text-white/15">分析パイプライン実行後にデータが表示されます</p>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string; color: string }) {
  const colors: Record<string, string> = {
    blue: "from-blue-500/10 to-blue-600/5 border-blue-500/10",
    violet: "from-violet-500/10 to-violet-600/5 border-violet-500/10",
    emerald: "from-emerald-500/10 to-emerald-600/5 border-emerald-500/10",
    orange: "from-orange-500/10 to-orange-600/5 border-orange-500/10",
  };
  const dots: Record<string, string> = {
    blue: "bg-blue-500", violet: "bg-violet-500", emerald: "bg-emerald-500", orange: "bg-orange-500",
  };
  return (
    <div className={`rounded-2xl border bg-gradient-to-br p-4 ${colors[color]}`}>
      <div className="flex items-center gap-1.5">
        <span className={`h-1.5 w-1.5 rounded-full ${dots[color]}`} />
        <span className="text-[11px] text-white/40">{label}</span>
      </div>
      <p className="mt-2 text-2xl font-semibold tracking-tight">{value}</p>
    </div>
  );
}
