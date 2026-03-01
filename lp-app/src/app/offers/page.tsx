"use client";

import { useState, useEffect, useCallback } from "react";
import AppShell from "@/components/AppShell";

interface OfferEntry {
  runId: string;
  offerName: string;
  target: string;
  price: string;
  rank: string;
  emailSent: number;
  emailReplied: number;
  inquiries: number;
  elapsedDays: number;
  status: string;
  lpUrl: string;
}

const RANK_COLORS: Record<string, string> = {
  A: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  B: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  C: "bg-orange-500/15 text-orange-400 border-orange-500/30",
  D: "bg-red-500/15 text-red-400 border-red-500/30",
};

const STATUS_COLORS: Record<string, string> = {
  active: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  pending_approval: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  draft: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  stopped: "bg-white/5 text-white/40 border-white/10",
  rejected: "bg-red-500/10 text-red-400 border-red-500/20",
  archived: "bg-white/5 text-white/30 border-white/10",
};

const STATUS_LABELS: Record<string, string> = {
  active: "稼働中",
  pending_approval: "承認待ち",
  draft: "生成中",
  stopped: "停止中",
  rejected: "却下",
  archived: "アーカイブ",
};

export default function OffersPage() {
  const [offers, setOffers] = useState<OfferEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>("active");

  const fetchOffers = useCallback(async () => {
    try {
      const res = await fetch("/api/offers");
      if (res.ok) {
        const data = await res.json();
        setOffers(data.offers || []);
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { fetchOffers(); }, [fetchOffers]);

  const filtered = statusFilter === "all"
    ? offers
    : offers.filter((o) => o.status === statusFilter);

  const counts = {
    active: offers.filter((o) => o.status === "active").length,
    pending_approval: offers.filter((o) => o.status === "pending_approval").length,
    draft: offers.filter((o) => o.status === "draft").length,
    stopped: offers.filter((o) => o.status === "stopped").length,
    rejected: offers.filter((o) => o.status === "rejected").length,
  };

  return (
    <AppShell>
      <main className="mx-auto max-w-5xl space-y-6 p-6">
        <h1 className="text-lg font-bold">オファー管理</h1>

        {/* Summary */}
        <div className="grid grid-cols-5 gap-2">
          {Object.entries(counts).map(([key, count]) => (
            <button
              key={key}
              onClick={() => setStatusFilter(key)}
              className={`rounded-xl border p-3 text-center transition-colors ${
                statusFilter === key ? "border-blue-500/40 bg-blue-500/10" : "border-white/[.06] bg-white/[.02] hover:bg-white/[.04]"
              }`}
            >
              <p className="text-lg font-bold">{count}</p>
              <p className="text-[9px] text-white/40">{STATUS_LABELS[key] || key}</p>
            </button>
          ))}
        </div>

        {loading && (
          <div className="flex justify-center py-20">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-blue-500" />
          </div>
        )}

        {!loading && filtered.length === 0 && (
          <div className="rounded-2xl border border-white/[.06] bg-white/[.02] p-10 text-center">
            <p className="text-sm text-white/30">該当するオファーはありません</p>
          </div>
        )}

        {!loading && filtered.length > 0 && (
          <div className="space-y-2">
            {/* Header */}
            <div className="hidden sm:grid grid-cols-12 gap-2 px-4 text-[9px] text-white/30">
              <span className="col-span-3">オファー名</span>
              <span className="col-span-2">ターゲット</span>
              <span>価格</span>
              <span>ランク</span>
              <span>送信</span>
              <span>返信</span>
              <span>問合せ</span>
              <span>稼働日数</span>
              <span>ステータス</span>
            </div>

            {filtered.map((o) => (
              <div key={o.runId} className="rounded-xl border border-white/[.06] bg-white/[.02] p-4 sm:grid sm:grid-cols-12 sm:gap-2 sm:items-center">
                <div className="col-span-3">
                  <p className="text-xs font-medium text-white/90 truncate">{o.offerName}</p>
                  {o.lpUrl && (
                    <a href={o.lpUrl} target="_blank" rel="noopener noreferrer" className="text-[9px] text-blue-400 hover:underline">
                      LP
                    </a>
                  )}
                </div>
                <p className="col-span-2 text-[10px] text-white/50 truncate">{o.target}</p>
                <p className="text-[10px] text-white/50">{o.price}</p>
                <span className={`inline-flex rounded-full border px-1.5 py-0.5 text-[9px] font-bold ${RANK_COLORS[o.rank] || "bg-white/5 text-white/30 border-white/10"}`}>
                  {o.rank || "-"}
                </span>
                <p className="text-xs text-white/70 text-center">{o.emailSent}</p>
                <p className="text-xs text-white/70 text-center">{o.emailReplied}</p>
                <p className="text-xs text-white/70 text-center">{o.inquiries}</p>
                <p className="text-[10px] text-white/40 text-center">{o.elapsedDays}日</p>
                <span className={`inline-flex rounded-full border px-1.5 py-0.5 text-[9px] font-medium ${STATUS_COLORS[o.status] || ""}`}>
                  {STATUS_LABELS[o.status] || o.status}
                </span>
              </div>
            ))}
          </div>
        )}
      </main>
    </AppShell>
  );
}
