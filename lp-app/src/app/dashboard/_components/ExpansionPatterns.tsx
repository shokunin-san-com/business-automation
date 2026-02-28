"use client";

import type { ExpansionData } from "../_types/dashboard";

interface Props {
  expansion: ExpansionData | undefined;
}

export function ExpansionPatterns({ expansion }: Props) {
  if (!expansion || expansion.totalPatterns === 0) return null;

  return (
    <section className="rounded-2xl border border-violet-500/20 bg-gradient-to-r from-violet-500/[.04] to-purple-500/[.04] p-5">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-bold text-violet-300">拡張層 — 勝ちパターン</h3>
        <span className="text-[10px] text-white/30">{expansion.activePatterns}件アクティブ / {expansion.scalingPatterns}件スケーリング中</span>
      </div>
      <div className="space-y-2">
        {expansion.patterns.map((p, i) => (
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
  );
}
