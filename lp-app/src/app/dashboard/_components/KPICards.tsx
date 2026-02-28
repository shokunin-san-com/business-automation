"use client";

import type { DashboardData } from "../_types/dashboard";

interface Props {
  data: DashboardData;
}

export function KPICards({ data }: Props) {
  const totalSns = data.activeBusinesses.reduce((s, b) => s + b.stats.snsPostCount, 0);
  const totalForm = data.activeBusinesses.reduce((s, b) => s + b.stats.formSubmitCount, 0);

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <KPICard label="アクティブ事業案" value={data.activeBusinesses.length} color="blue" />
      <KPICard label="問い合わせ" value={data.downstream?.totalInquiries ?? 0} color="orange" />
      <KPICard
        label="成約率"
        value={data.downstream?.dealRate ? `${(data.downstream.dealRate * 100).toFixed(0)}%` : "0%"}
        color="emerald"
      />
      <KPICard label="SNS投稿" value={totalSns} color="cyan" />
      <KPICard label="フォーム送信" value={totalForm} color="violet" />
      <KPICard label="勝ちパターン" value={data.expansion?.activePatterns ?? 0} color="pink" />
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
