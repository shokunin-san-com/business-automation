"use client";

import type { DownstreamData, ActiveBusiness } from "../_types/dashboard";

interface Props {
  downstream: DownstreamData | undefined;
  activeBusinesses: ActiveBusiness[];
}

export function DownstreamFunnel({ downstream, activeBusinesses }: Props) {
  if (!downstream) return null;

  const totalSns = activeBusinesses.reduce((s, b) => s + b.stats.snsPostCount, 0);
  const totalForm = activeBusinesses.reduce((s, b) => s + b.stats.formSubmitCount, 0);
  const totalBlog = activeBusinesses.reduce((s, b) => s + b.stats.blogArticleCount, 0);

  return (
    <section className="rounded-2xl border border-white/[.08] bg-white/[.03] p-5">
      <h3 className="mb-3 text-sm font-bold text-white/90">ファネル</h3>

      {/* 活動量サマリー */}
      <div className="mb-4 flex gap-4 text-[11px] text-white/50">
        <span>SNS投稿: <span className="text-cyan-400 font-medium">{totalSns}</span></span>
        <span>フォーム送信: <span className="text-violet-400 font-medium">{totalForm}</span></span>
        <span>ブログ記事: <span className="text-pink-400 font-medium">{totalBlog}</span></span>
      </div>

      {/* ファネルバー */}
      <div className="flex items-end gap-2">
        {[
          { label: "問い合わせ", value: downstream.totalInquiries, color: "bg-blue-500" },
          { label: "適格", value: downstream.qualifiedInquiries, color: "bg-cyan-500" },
          { label: "商談中", value: downstream.activeDeals, color: "bg-amber-500" },
          { label: "成約", value: downstream.wonDeals, color: "bg-emerald-500" },
          { label: "失注", value: downstream.lostDeals, color: "bg-red-500" },
        ].map((step) => {
          const maxVal = Math.max(downstream.totalInquiries, 1);
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

      {/* 全部0のとき */}
      {downstream.totalInquiries === 0 && totalSns === 0 && totalForm === 0 && (
        <p className="mt-3 text-center text-[11px] text-white/20">
          まだ活動実績がありません
        </p>
      )}

      {downstream.totalDealValue > 0 && (
        <p className="mt-3 text-center text-xs text-white/50">
          成約金額合計: <span className="font-semibold text-emerald-400">{downstream.totalDealValue.toLocaleString()}円</span>
        </p>
      )}
    </section>
  );
}
