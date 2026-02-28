"use client";

import type { V2Data, PendingIdea } from "../_types/dashboard";

interface Props {
  v2: V2Data | undefined;
  pendingIdeas: PendingIdea[];
  approving: string | null;
  onApprove: (ideaId: string, action: "approve" | "reject") => Promise<void>;
}

export function V2CommandCenter({ v2, pendingIdeas, approving, onApprove }: Props) {
  return (
    <section className="space-y-3">
      {/* Pending Approval Banner */}
      {pendingIdeas.length > 0 && (
        <div className="rounded-2xl border border-amber-500/20 bg-gradient-to-r from-amber-500/[.06] to-orange-500/[.04] p-5">
          <div className="mb-3 flex items-center gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-amber-500/20 text-[10px]">{"\u23F3"}</span>
            <h2 className="text-sm font-semibold text-amber-300">承認待ち — {pendingIdeas.length}件の事業案</h2>
          </div>
          <div className="space-y-2.5">
            {pendingIdeas.map((idea) => (
              <div key={idea.id} className="rounded-xl bg-black/30 p-4">
                <div className="flex items-start gap-4">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-sm">{idea.name}</p>
                    <p className="mt-0.5 text-xs text-white/40">{idea.description}</p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <span className="rounded-md bg-white/5 px-2 py-0.5 text-[10px] text-white/50">
                        支払者: {idea.target_audience}
                      </span>
                      {idea.evidenceCount !== undefined && (
                        <span className="rounded-md bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-400">
                          エビデンス {idea.evidenceCount}件
                        </span>
                      )}
                    </div>
                    {/* オファー一覧 */}
                    {idea.offers && idea.offers.length > 0 && (
                      <div className="mt-2 space-y-1 border-t border-white/[.06] pt-2">
                        {idea.offers.map((o, i) => (
                          <div key={i} className="flex items-center gap-2 text-[10px]">
                            <span className="text-white/50">#{i + 1}</span>
                            <span className="text-white/70 font-medium">{o.offerName}</span>
                            {o.price && <span className="text-white/40">{o.price}</span>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <button
                      onClick={() => onApprove(idea.id, "approve")}
                      disabled={approving === idea.id}
                      className="rounded-lg bg-emerald-600 px-3.5 py-1.5 text-xs font-medium text-white transition-all hover:bg-emerald-500 disabled:opacity-50"
                    >
                      {approving === idea.id ? "..." : "承認"}
                    </button>
                    <button
                      onClick={() => onApprove(idea.id, "reject")}
                      disabled={approving === idea.id}
                      className="rounded-lg bg-white/5 px-3.5 py-1.5 text-xs font-medium text-white/60 transition-all hover:bg-white/10 disabled:opacity-50"
                    >
                      却下
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* V2 Command Center */}
      {v2 && (
        <>
          {/* Scoring Warnings */}
          {v2.scoringWarnings.length > 0 && (
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4">
              <h3 className="mb-2 text-sm font-bold text-red-400">{"\u{1F6A8}"} 方針矛盾チェッカー</h3>
              {v2.scoringWarnings.map((w, i) => (
                <p key={i} className="text-xs text-red-300">{w}</p>
              ))}
            </div>
          )}

          {/* Run Summary */}
          {v2.latestRunId && (
            <div className="rounded-xl border border-white/[.08] bg-white/[.03] p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-bold text-white/90">{"\u{1F3AF}"} V2 司令塔</h3>
                <span className="text-[10px] text-white/40 font-mono">run: {v2.latestRunId.slice(0, 8)}</span>
              </div>

              {/* Gate Results */}
              <div className="mb-3">
                <p className="text-xs text-white/50 mb-1">ゲート結果</p>
                <div className="flex flex-wrap gap-2">
                  {v2.gateResults.map((g, i) => (
                    <span
                      key={i}
                      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                        g.status === "PASS"
                          ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                          : "bg-red-500/10 text-red-400 border border-red-500/20"
                      }`}
                    >
                      {g.status === "PASS" ? "\u2705" : "\u274C"} {(g.micro_market || "").slice(0, 25)}
                    </span>
                  ))}
                  {v2.gateResults.length === 0 && (
                    <span className="text-[11px] text-white/30">まだ実行されていません</span>
                  )}
                </div>
              </div>

              {/* Offers */}
              {v2.offers.length > 0 && (
                <div className="mb-3">
                  <p className="text-xs text-white/50 mb-1">オファー3案</p>
                  <div className="space-y-1">
                    {v2.offers.map((o, i) => (
                      <div key={i} className="flex items-center gap-2 text-[11px]">
                        <span className="text-white/70">#{o.offer_num}</span>
                        <span className="text-white/90 font-medium">{o.offer_name}</span>
                        <span className="text-white/40">{o.price}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* LP Ready Status */}
              <div className="flex items-center gap-2">
                <span className="text-xs text-white/50">LP作成:</span>
                <span
                  className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                    v2.lpReadyStatus === "READY"
                      ? "bg-emerald-500/15 text-emerald-400"
                      : v2.lpReadyStatus === "BLOCKED"
                        ? "bg-red-500/10 text-red-400"
                        : "bg-white/5 text-white/30"
                  }`}
                >
                  {v2.lpReadyStatus || "未実行"}
                </span>
              </div>

              {/* CEO Review Needed */}
              {(v2.ceoReviewNeeded.market || v2.ceoReviewNeeded.offer) && (
                <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
                  <p className="text-xs font-bold text-amber-400 mb-1">{"\u{1F454}"} CEO承認が必要です</p>
                  {v2.ceoReviewNeeded.market && (
                    <p className="text-[11px] text-amber-300/80">
                      • PASS市場が複数あります。却下して1つに絞ってください。
                    </p>
                  )}
                  {v2.ceoReviewNeeded.offer && (
                    <p className="text-[11px] text-amber-300/80">
                      • オファーが複数あります。却下して絞ってください。
                    </p>
                  )}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
