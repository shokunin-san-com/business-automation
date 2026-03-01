"use client";

import type { V2Data, PendingIdea } from "../_types/dashboard";

interface Props {
  v2: V2Data | undefined;
  pendingIdeas: PendingIdea[];
  approving: string | null;
  onApprove: (ideaId: string, action: "approve" | "reject") => Promise<void>;
}

function StepBadge({ status }: { status: string }) {
  if (status === "done") return <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />;
  if (status === "running") return <span className="h-2.5 w-2.5 rounded-full bg-blue-500 animate-pulse" />;
  if (status === "error") return <span className="h-2.5 w-2.5 rounded-full bg-red-500" />;
  return <span className="h-2.5 w-2.5 rounded-full bg-white/20" />;
}

export function V2CommandCenter({ v2, pendingIdeas, approving, onApprove }: Props) {
  return (
    <section className="space-y-3">
      {/* Pending Approval Banner */}
      {pendingIdeas.length > 0 && (
        <div className="rounded-2xl border border-amber-500/20 bg-gradient-to-r from-amber-500/[.06] to-orange-500/[.04] p-5">
          <div className="mb-3 flex items-center gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-amber-500/20 text-[10px]">{"\u23F3"}</span>
            <h2 className="text-sm font-semibold text-amber-300">{"\u627F\u8A8D\u5F85\u3061"} \u2014 {pendingIdeas.length}\u4EF6</h2>
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
                        {"\u652F\u6255\u8005"}: {idea.target_audience}
                      </span>
                      {idea.evidenceCount !== undefined && (
                        <span className="rounded-md bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-400">
                          {"\u30A8\u30D3\u30C7\u30F3\u30B9"} {idea.evidenceCount}\u4EF6
                        </span>
                      )}
                    </div>
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
                      {approving === idea.id ? "..." : "GO"}
                    </button>
                    <button
                      onClick={() => onApprove(idea.id, "reject")}
                      disabled={approving === idea.id}
                      className="rounded-lg bg-red-500/20 px-3.5 py-1.5 text-xs font-medium text-red-400 transition-all hover:bg-red-500/30 disabled:opacity-50 border border-red-500/20"
                    >
                      STOP
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* V3 Pipeline Center */}
      {v2 && (
        <>
          {v2.scoringWarnings.length > 0 && (
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4">
              <h3 className="mb-2 text-sm font-bold text-red-400">{"\u{1F6A8}"} {"\u65B9\u91DD\u77DB\u76FE\u30C1\u30A7\u30C3\u30AB\u30FC"}</h3>
              {v2.scoringWarnings.map((w, i) => (
                <p key={i} className="text-xs text-red-300">{w}</p>
              ))}
            </div>
          )}

          {v2.latestRunId && (
            <div className="rounded-xl border border-white/[.08] bg-white/[.03] p-4">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-bold text-white/90">{"\u{1F680}"} V3 {"\u30D1\u30A4\u30D7\u30E9\u30A4\u30F3"}</h3>
                <span className="text-[10px] text-white/40 font-mono">run: {v2.latestRunId.slice(0, 8)}</span>
              </div>

              {/* Pipeline Step Progress */}
              {v2.steps.length > 0 && (
                <div className="mb-4 flex items-center gap-1">
                  {v2.steps.map((step, i) => (
                    <div key={step.name} className="flex items-center gap-1">
                      <div className="flex flex-col items-center gap-1">
                        <StepBadge status={step.status} />
                        <span className="text-[8px] text-white/30 text-center whitespace-nowrap">
                          {step.name.replace(/Phase \w \(/, "(").replace(/\)/, "")}
                        </span>
                      </div>
                      {i < v2.steps.length - 1 && (
                        <div className={`h-px w-4 ${step.status === "done" ? "bg-emerald-500/50" : "bg-white/10"}`} />
                      )}
                    </div>
                  ))}
                </div>
              )}

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
                  <p className="text-xs text-white/50 mb-1">{"\u30AA\u30D5\u30A1\u30FC"}</p>
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
                <span className="text-xs text-white/50">LP{"\u4F5C\u6210"}:</span>
                <span
                  className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                    v2.lpReadyStatus === "READY"
                      ? "bg-emerald-500/15 text-emerald-400"
                      : v2.lpReadyStatus === "BLOCKED"
                        ? "bg-red-500/10 text-red-400"
                        : "bg-white/5 text-white/30"
                  }`}
                >
                  {v2.lpReadyStatus || "\u672A\u5B9F\u884C"}
                </span>
              </div>

              {/* CEO Review Needed */}
              {(v2.ceoReviewNeeded.market || v2.ceoReviewNeeded.offer) && (
                <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
                  <p className="text-xs font-bold text-amber-400 mb-1">{"\u{1F454}"} CEO{"\u627F\u8A8D\u304C\u5FC5\u8981\u3067\u3059"}</p>
                  <p className="text-[11px] text-amber-300/80">
                    /approval {"\u3067\u78BA\u8A8D\u3057\u3066\u304F\u3060\u3055\u3044\u3002"}
                  </p>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
