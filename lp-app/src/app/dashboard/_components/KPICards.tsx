"use client";

import type { DashboardData } from "../_types/dashboard";

interface Props {
  data: DashboardData;
}

export function KPICards({ data }: Props) {
  const totalEmailSent = data.activeBusinesses.reduce((s, b) => s + (b.stats.emailSentCount ?? 0), 0);
  const totalEmailReplied = data.activeBusinesses.reduce((s, b) => s + (b.stats.emailRepliedCount ?? 0), 0);
  const replyRate = totalEmailSent > 0 ? `${((totalEmailReplied / totalEmailSent) * 100).toFixed(0)}%` : "-";
  const activeOffers = data.activeBusinesses.reduce(
    (s, b) => s + (b.offers?.length ?? 0), 0,
  );
  const aRankCount = data.activeBusinesses.filter(
    (b) => (b as Record<string, unknown>).rank === "A",
  ).length;
  const apiCost = (data as Record<string, unknown>).monthlyCost as number | undefined;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <KPICard label="稼働中オファー" value={activeOffers} color="blue" />
      <KPICard label="メール送信数" value={totalEmailSent} color="cyan" />
      <KPICard label="メール返信数" value={totalEmailReplied} color="violet" />
      <KPICard label="問い合わせ" value={data.downstream?.totalInquiries ?? 0} color="orange" />
      <KPICard label="Aランク案件" value={aRankCount} color="emerald" />
      <KPICostCard label="今月APIコスト" value={apiCost ?? 0} limit={30000} />
    </div>
  );
}

function KPICard({ label, value, color }: { label: string; value: number | string; color: string }) {
  const gradients: Record<string, string> = {
    blue: "from-blue-500/10 to-blue-600/5 border-blue-500/10",
    violet: "from-violet-500/10 to-violet-600/5 border-violet-500/10",
    emerald: "from-emerald-500/10 to-emerald-600/5 border-emerald-500/10",
    orange: "from-orange-500/10 to-orange-600/5 border-orange-500/10",
    pink: "from-pink-500/10 to-pink-600/5 border-pink-500/10",
    cyan: "from-cyan-500/10 to-cyan-600/5 border-cyan-500/10",
  };
  const dotColors: Record<string, string> = {
    blue: "bg-blue-500",
    violet: "bg-violet-500",
    emerald: "bg-emerald-500",
    orange: "bg-orange-500",
    pink: "bg-pink-500",
    cyan: "bg-cyan-500",
  };
  return (
    <div className={`relative overflow-hidden rounded-2xl border bg-gradient-to-br p-4 ${gradients[color] || gradients.blue}`}>
      <div className="flex items-center gap-1.5">
        <span className={`h-1.5 w-1.5 rounded-full ${dotColors[color] || dotColors.blue}`} />
        <span className="text-[11px] text-white/40 tracking-wide">{label}</span>
      </div>
      <p className="mt-2 text-2xl font-semibold tracking-tight">{value}</p>
    </div>
  );
}

function KPICostCard({ label, value, limit }: { label: string; value: number; limit: number }) {
  const pct = Math.min((value / limit) * 100, 100);
  const barColor = pct > 80 ? "bg-red-500" : pct > 50 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="relative overflow-hidden rounded-2xl border bg-gradient-to-br from-white/[.04] to-white/[.02] border-white/[.08] p-4">
      <div className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-white/30" />
        <span className="text-[11px] text-white/40 tracking-wide">{label}</span>
      </div>
      <p className="mt-2 text-xl font-semibold tracking-tight">
        {"\u00A5"}{value.toLocaleString()}
      </p>
      <div className="mt-2 h-1 w-full rounded-full bg-white/10">
        <div className={`h-full rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-1 text-[9px] text-white/30">上限 {"\u00A5"}{limit.toLocaleString()}</p>
    </div>
  );
}
