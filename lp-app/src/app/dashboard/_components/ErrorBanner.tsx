"use client";

import type { DataFetchError } from "../_types/dashboard";

interface Props {
  errors: DataFetchError[];
}

const SECTION_LABELS: Record<string, string> = {
  pipeline: "パイプライン状態",
  lp: "LP情報",
  pendingIdeas: "承認待ち",
  scheduler: "スケジューラー",
  v2: "V2パイプライン",
  downstream: "下流指標",
  expansion: "拡張層",
  activeBusinesses: "アクティブ事業案",
  blog: "ブログ記事",
  global: "全体",
};

export function ErrorBanner({ errors }: Props) {
  if (!errors || errors.length === 0) return null;

  return (
    <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-4">
      <p className="text-xs font-semibold text-red-400 mb-2">
        データ取得エラー ({errors.length}件)
      </p>
      <div className="space-y-1">
        {errors.map((e, i) => (
          <p key={i} className="text-[11px] text-red-300/70">
            {SECTION_LABELS[e.section] || e.section}: {e.message}
          </p>
        ))}
      </div>
    </div>
  );
}
