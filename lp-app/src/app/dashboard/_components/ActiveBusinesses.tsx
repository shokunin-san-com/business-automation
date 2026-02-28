"use client";

import type { ActiveBusiness } from "../_types/dashboard";

function formatTime(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("ja-JP", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

interface Props {
  businesses: ActiveBusiness[];
}

export function ActiveBusinesses({ businesses }: Props) {
  if (businesses.length === 0) {
    return (
      <section className="rounded-2xl border border-white/[.06] bg-white/[.02] p-6 text-center">
        <p className="text-sm text-white/30">アクティブな事業案はありません</p>
        <p className="mt-1 text-[10px] text-white/20">
          V2パイプラインを実行してゲート通過 → LP READY まで進めてください
        </p>
      </section>
    );
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-white/80">
          アクティブ事業案 ({businesses.length})
        </h2>
      </div>

      {businesses.map((biz) => {
        const stats = biz.stats;
        const totalActivity = stats.snsPostCount + stats.formSubmitCount + stats.blogArticleCount;
        return (
          <div
            key={biz.runId}
            className="rounded-2xl border border-white/[.08] bg-white/[.03] p-5"
          >
            {/* ヘッダー: 市場名 + 支払者 */}
            <div className="flex items-start justify-between mb-4">
              <div>
                <p className="text-sm font-semibold text-white/90">{biz.marketName}</p>
                <p className="text-[11px] text-white/40 mt-0.5">
                  支払者: {biz.payer || "未定義"} / ゲート通過: {formatTime(biz.gatePassedAt)}
                </p>
              </div>
              <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-400 border border-emerald-500/30">
                ACTIVE
              </span>
            </div>

            {/* オファー一覧 */}
            {biz.offers.length > 0 && (
              <div className="mb-4 space-y-1">
                {biz.offers.map((o, i) => (
                  <div key={i} className="flex items-center gap-2 text-[11px]">
                    <span className="text-white/50">#{i + 1}</span>
                    <span className="text-white/80 font-medium">{o.offerName}</span>
                    <span className="text-white/40">{o.deliverable}</span>
                    {o.price && <span className="text-emerald-400/70">{o.price}</span>}
                  </div>
                ))}
              </div>
            )}

            {/* LP URLs */}
            {biz.lpUrls.length > 0 && (
              <div className="mb-4 flex flex-wrap gap-2">
                {biz.lpUrls.map((url, i) => (
                  <a
                    key={i}
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 rounded-md bg-blue-500/10 px-2 py-0.5 text-[10px] text-blue-400 border border-blue-500/20 hover:bg-blue-500/20 transition-colors"
                  >
                    LP {i + 1}
                  </a>
                ))}
              </div>
            )}

            {/* 活動実績グリッド */}
            <div className="grid grid-cols-4 gap-2 sm:grid-cols-8">
              <StatCell label="LP" value={stats.lpCount} color="blue" />
              <StatCell label="SNS投稿" value={stats.snsPostCount} color="cyan" />
              <StatCell label="フォーム送信" value={stats.formSubmitCount} color="violet" />
              <StatCell label="フォーム返信" value={stats.formResponseCount} color="purple" />
              <StatCell label="ブログ" value={stats.blogArticleCount} color="pink" />
              <StatCell label="問い合わせ" value={stats.inquiryCount} color="amber" />
              <StatCell label="成約" value={stats.dealWonCount} color="emerald" />
              <StatCell label="失注" value={stats.dealLostCount} color="red" />
            </div>

            {/* 活動ゼロ警告 */}
            {totalActivity === 0 && (
              <div className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 p-2">
                <p className="text-[10px] text-amber-400/80">
                  まだ配信活動がありません。LP生成 → SNS/フォーム営業を実行してください。
                </p>
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}

function StatCell({ label, value, color }: { label: string; value: number; color: string }) {
  const colorMap: Record<string, string> = {
    blue: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    cyan: "bg-cyan-500/10 text-cyan-400 border-cyan-500/20",
    violet: "bg-violet-500/10 text-violet-400 border-violet-500/20",
    purple: "bg-purple-500/10 text-purple-400 border-purple-500/20",
    pink: "bg-pink-500/10 text-pink-400 border-pink-500/20",
    amber: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    emerald: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    red: "bg-red-500/10 text-red-400 border-red-500/20",
  };
  return (
    <div className={`rounded-lg border p-2 text-center ${colorMap[color] || ""}`}>
      <p className="text-lg font-semibold">{value}</p>
      <p className="text-[9px] mt-0.5 opacity-70">{label}</p>
    </div>
  );
}
