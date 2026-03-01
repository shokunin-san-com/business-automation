"use client";

import { useState, useEffect, useCallback } from "react";
import AppShell from "@/components/AppShell";

interface ApprovalItem {
  run_id: string;
  offer_name: string;
  lp_url: string;
  email_subject: string;
  email_body: string;
  ceo_decision: string;
  decided_at: string;
}

export default function ApprovalPage() {
  const [items, setItems] = useState<ApprovalItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"pending" | "all">("pending");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [deciding, setDeciding] = useState<string | null>(null);

  const fetchItems = useCallback(async () => {
    try {
      const res = await fetch("/api/approval");
      if (res.ok) {
        const data = await res.json();
        setItems(data.items || []);
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { fetchItems(); }, [fetchItems]);

  const handleDecision = async (runId: string, decision: "GO" | "STOP") => {
    setDeciding(runId);
    try {
      await fetch("/api/approval", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, decision }),
      });
      await fetchItems();
    } catch { /* ignore */ }
    setDeciding(null);
  };

  const filtered = filter === "pending"
    ? items.filter((i) => !i.ceo_decision)
    : items;

  return (
    <AppShell>
      <main className="mx-auto max-w-4xl space-y-6 p-6">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-bold">CEO承認</h1>
          <div className="flex gap-2">
            <button
              onClick={() => setFilter("pending")}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                filter === "pending" ? "bg-white/[.08] text-white" : "text-white/40 hover:text-white/60"
              }`}
            >
              未判定のみ
            </button>
            <button
              onClick={() => setFilter("all")}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                filter === "all" ? "bg-white/[.08] text-white" : "text-white/40 hover:text-white/60"
              }`}
            >
              全件
            </button>
          </div>
        </div>

        {loading && (
          <div className="flex justify-center py-20">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-blue-500" />
          </div>
        )}

        {!loading && filtered.length === 0 && (
          <div className="rounded-2xl border border-white/[.06] bg-white/[.02] p-10 text-center">
            <p className="text-sm text-white/30">承認待ちの案件はありません</p>
            <p className="mt-1 text-[10px] text-white/20">
              V3パイプラインがオファーを生成すると、ここに表示されます
            </p>
          </div>
        )}

        {!loading && filtered.map((item) => {
          const isExpanded = expandedId === item.run_id;
          const isPending = !item.ceo_decision;
          return (
            <div key={item.run_id} className="rounded-2xl border border-white/[.08] bg-white/[.03] p-5">
              <div className="flex items-start justify-between">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-white/90">{item.offer_name || item.run_id.slice(0, 8)}</p>
                  {item.email_subject && (
                    <p className="mt-1 text-[11px] text-white/40">件名: {item.email_subject}</p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {item.ceo_decision && (
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
                      item.ceo_decision === "GO"
                        ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                        : "bg-red-500/15 text-red-400 border border-red-500/30"
                    }`}>
                      {item.ceo_decision}
                    </span>
                  )}
                </div>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                {item.lp_url && (
                  <a
                    href={item.lp_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 rounded-md bg-blue-500/10 px-2.5 py-1 text-[10px] text-blue-400 border border-blue-500/20 hover:bg-blue-500/20 transition-colors"
                  >
                    LPプレビュー
                  </a>
                )}
                <button
                  onClick={() => setExpandedId(isExpanded ? null : item.run_id)}
                  className="inline-flex items-center gap-1 rounded-md bg-white/5 px-2.5 py-1 text-[10px] text-white/50 border border-white/10 hover:bg-white/10 transition-colors"
                >
                  {isExpanded ? "メール本文を閉じる" : "メール本文を見る"}
                </button>
              </div>

              {isExpanded && item.email_body && (
                <div className="mt-3 rounded-lg bg-black/30 p-4 text-[11px] text-white/60 whitespace-pre-wrap leading-relaxed">
                  {item.email_body}
                </div>
              )}

              {isPending && (
                <div className="mt-4 flex gap-2 border-t border-white/[.06] pt-4">
                  <button
                    onClick={() => handleDecision(item.run_id, "GO")}
                    disabled={deciding === item.run_id}
                    className="rounded-lg bg-emerald-600 px-5 py-2 text-xs font-bold text-white transition-all hover:bg-emerald-500 disabled:opacity-50"
                  >
                    {deciding === item.run_id ? "..." : "GO"}
                  </button>
                  <button
                    onClick={() => handleDecision(item.run_id, "STOP")}
                    disabled={deciding === item.run_id}
                    className="rounded-lg bg-red-500/20 px-5 py-2 text-xs font-bold text-red-400 transition-all hover:bg-red-500/30 disabled:opacity-50 border border-red-500/20"
                  >
                    STOP
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </main>
    </AppShell>
  );
}
