"use client";

import type { ScriptInfo, SchedulerInfo } from "../_types/dashboard";

const STATUS_DOT: Record<string, string> = {
  running: "bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,.6)] animate-pulse",
  success: "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,.5)]",
  error: "bg-red-500 shadow-[0_0_6px_rgba(239,68,68,.5)]",
  idle: "bg-white/20",
};

const STATUS_BADGE: Record<string, { bg: string; text: string; label: string }> = {
  running: { bg: "bg-blue-500/15 border-blue-500/30", text: "text-blue-400", label: "実行中" },
  success: { bg: "bg-emerald-500/15 border-emerald-500/30", text: "text-emerald-400", label: "完了" },
  error: { bg: "bg-red-500/15 border-red-500/30", text: "text-red-400", label: "エラー" },
  idle: { bg: "bg-white/5 border-white/10", text: "text-white/40", label: "待機中" },
};

const PIPELINE_META: Record<string, { icon: string; schedule: string; schedulers: string[] }> = {
  orchestrate_v2: { icon: "\u{1F52C}", schedule: "", schedulers: [] },
  "1_lp_generator": { icon: "\u{1F680}", schedule: "毎日 09:00", schedulers: ["schedule-lp-generator"] },
  "2_sns_poster": { icon: "\u{1F4E2}", schedule: "毎日 10:00 / 18:00", schedulers: ["schedule-sns-morning", "schedule-sns-evening"] },
  "3_form_sales": { icon: "\u2709\uFE0F", schedule: "平日 11:00", schedulers: ["schedule-form-sales"] },
  "4_analytics_reporter": { icon: "\u{1F4C8}", schedule: "毎日 01:00", schedulers: ["schedule-analytics"] },
  "5_slack_reporter": { icon: "\u{1F4AC}", schedule: "毎週月曜 08:00", schedulers: ["schedule-slack-report"] },
  "7_learning_engine": { icon: "\u{1F9E0}", schedule: "毎日 19:00", schedulers: ["schedule-learning-engine"] },
  "9_expansion_engine": { icon: "\u{1F680}", schedule: "毎日 03:00", schedulers: ["schedule-expansion-engine"] },
};

const SCHEDULER_LABEL: Record<string, string> = {
  "schedule-sns-morning": "朝",
  "schedule-sns-evening": "夕",
};

const SCHEDULE_PRESETS = [
  { label: "毎日 6:00", cron: "0 6 * * *" },
  { label: "毎日 9:00", cron: "0 9 * * *" },
  { label: "6時間毎", cron: "0 */6 * * *" },
  { label: "12時間毎", cron: "0 */12 * * *" },
  { label: "毎週月曜 8:00", cron: "0 8 * * 1" },
];

function cronToJapanese(cron: string): string {
  if (!cron) return "";
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return cron;
  const [minute, hour, day, month, weekday] = parts;

  const weekdayNames: Record<string, string> = {
    "0": "日", "1": "月", "2": "火", "3": "水", "4": "木", "5": "金", "6": "土", "7": "日",
  };

  if (hour.startsWith("*/") && minute === "0" && day === "*" && month === "*" && weekday === "*") {
    return `${hour.slice(2)}時間毎`;
  }
  if (day === "*" && month === "*" && weekday === "*" && !hour.includes("/") && !minute.includes("/")) {
    return `毎日 ${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
  }
  if (day === "*" && month === "*" && weekday !== "*" && !hour.includes("/")) {
    const dayName = weekdayNames[weekday] || weekday;
    return `毎週${dayName}曜 ${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
  }
  if (day === "*" && month === "*" && weekday === "1-5" && !hour.includes("/")) {
    return `平日 ${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
  }
  return cron;
}

function formatTime(iso: string): string {
  if (!iso) return "\u2014";
  const d = new Date(iso);
  return d.toLocaleString("ja-JP", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function relativeTime(iso: string): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "たった今";
  if (mins < 60) return `${mins}分前`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}時間前`;
  return `${Math.floor(hrs / 24)}日前`;
}

const METRIC_LABELS: Record<string, string> = {
  micro_markets_generated: "生成マイクロ市場",
  a1q_passed: "A1q通過",
  a1q_failed: "A1q不合格",
  a1d_passed: "A1dゲート通過",
  a1d_failed: "A1dゲート不合格",
  exploration_lanes: "探索レーン",
  competitors_20: "競合20社分析",
  gap_top3: "穴トップ3",
  offers_generated: "即決オファー",
  lp_ready: "LP作成可",
  lp_blocked: "LP作成不可",
  segments_researched: "調査セグメント",
  markets_scored: "スコアリング市場",
  competitors_analyzed: "競合分析",
  markets_processed: "処理市場",
  ideas_generated: "生成アイデア",
  lps_generated: "生成LP",
  posted: "投稿",
  reviewed: "レビュー済",
  blocked: "ブロック",
  sent: "送信",
  suggestions: "提案",
  total_pageviews: "総PV",
  lps_analyzed: "分析LP",
  bid_adjustments: "入札調整",
  kill_flagged: "損切り対象",
  downstream_inquiries: "問い合わせ",
  downstream_deals_won: "成約",
  downstream_deal_rate: "成約率",
  patterns_detected: "パターン検出",
  sops_generated: "SOP生成",
  v2_insights: "V2インサイト",
};

interface Props {
  pipeline: ScriptInfo[];
  schedulerStatus: Record<string, SchedulerInfo>;
  executing: string | null;
  onExecute: (scriptId: string) => Promise<void>;
  onSchedulerToggle: (schedulerName: string, currentState: string) => Promise<void>;
  togglingScheduler: string | null;
  onScheduleEdit: (target: { schedulerName: string; scriptLabel: string; currentCron: string }) => void;
}

export { PIPELINE_META, SCHEDULE_PRESETS, SCHEDULER_LABEL, cronToJapanese, formatTime, relativeTime };

export function PipelineCards({
  pipeline,
  schedulerStatus,
  executing,
  onExecute,
  onSchedulerToggle,
  togglingScheduler,
  onScheduleEdit,
}: Props) {
  return (
    <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {pipeline.map((script) => {
        const meta = PIPELINE_META[script.id] || { icon: "\u2699\uFE0F", schedule: "", schedulers: [] };
        const badge = STATUS_BADGE[script.status] || STATUS_BADGE.idle;
        const isExecuting = executing === script.id;

        const scriptSchedulers = meta.schedulers;
        const allScriptSchedulersEnabled = scriptSchedulers.every(
          (name) => schedulerStatus[name]?.state === "ENABLED",
        );
        const isTogglingAny = scriptSchedulers.some(
          (name) => togglingScheduler === name,
        );

        return (
          <div
            key={script.id}
            className="group relative overflow-hidden rounded-2xl border border-white/[.06] bg-white/[.02] p-5 transition-all hover:border-white/[.12] hover:bg-white/[.04]"
          >
            {script.status === "running" && (
              <div className="absolute -top-20 -right-20 h-40 w-40 rounded-full bg-blue-500/10 blur-3xl" />
            )}

            <div className="relative flex items-start justify-between">
              <div className="flex items-center gap-3">
                <span className="text-xl">{meta.icon}</span>
                <div>
                  <p className="text-sm font-medium">{script.label}</p>
                  <div className="flex items-center gap-1.5 flex-wrap">
                    {scriptSchedulers.length <= 1 ? (
                      <>
                        <p className="text-[10px] text-white/30">
                          {(() => {
                            const firstScheduler = scriptSchedulers[0];
                            const realCron = firstScheduler ? schedulerStatus[firstScheduler]?.schedule : "";
                            return realCron ? cronToJapanese(realCron) : meta.schedule;
                          })()}
                        </p>
                        {scriptSchedulers.length === 1 && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              const name = scriptSchedulers[0];
                              const currentCron = schedulerStatus[name]?.schedule || "";
                              onScheduleEdit({
                                schedulerName: name,
                                scriptLabel: script.label,
                                currentCron,
                              });
                            }}
                            className="text-[9px] text-white/20 hover:text-blue-400 transition-colors"
                            title="スケジュール編集"
                          >
                            {"\u270F\uFE0F"}
                          </button>
                        )}
                      </>
                    ) : (
                      <div className="flex flex-col gap-0.5">
                        {scriptSchedulers.map((name) => {
                          const realCron = schedulerStatus[name]?.schedule || "";
                          const suffix = SCHEDULER_LABEL[name] || name.replace(/^schedule-/, "");
                          return (
                            <div key={name} className="flex items-center gap-1">
                              <p className="text-[10px] text-white/30">
                                {suffix}: {realCron ? cronToJapanese(realCron) : "—"}
                              </p>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  const currentCron = schedulerStatus[name]?.schedule || "";
                                  onScheduleEdit({
                                    schedulerName: name,
                                    scriptLabel: `${script.label}（${suffix}）`,
                                    currentCron,
                                  });
                                }}
                                className="text-[9px] text-white/20 hover:text-blue-400 transition-colors"
                                title={`${suffix}スケジュール編集`}
                              >
                                {"\u270F\uFE0F"}
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>
              </div>
              <div className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-medium ${badge.bg} ${badge.text}`}>
                <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT[script.status] || STATUS_DOT.idle}`} />
                {badge.label}
              </div>
            </div>

            {script.detail && (
              <p className="relative mt-3 truncate text-xs text-white/40">{script.detail}</p>
            )}

            <div className="relative mt-3 flex items-center justify-between text-[10px] text-white/20">
              <span>{formatTime(script.lastRun)}</span>
              {script.lastRun && <span>{relativeTime(script.lastRun)}</span>}
            </div>

            {Object.keys(script.metrics).length > 0 && (
              <div className="relative mt-3 flex flex-wrap gap-2 border-t border-white/[.06] pt-3">
                {Object.entries(script.metrics)
                  .filter(([, v]) => typeof v !== "object" || v === null)
                  .map(([k, v]) => (
                  <span key={k} className="rounded-md bg-white/5 px-2 py-0.5 text-[10px] text-white/40">
                    {METRIC_LABELS[k] || k.replace(/_/g, " ")}: <span className="text-white/70 font-medium">{String(v)}</span>
                  </span>
                ))}
              </div>
            )}

            {/* Action Bar */}
            <div className="relative mt-4 flex items-center justify-between border-t border-white/[.06] pt-3">
              <button
                onClick={() => onExecute(script.id)}
                disabled={isExecuting || script.status === "running"}
                className="flex items-center gap-1.5 rounded-lg bg-blue-600/20 px-3 py-1.5 text-[11px] font-medium text-blue-400 transition-all hover:bg-blue-600/30 disabled:opacity-40 disabled:cursor-not-allowed border border-blue-500/20"
              >
                {isExecuting ? (
                  <>
                    <span className="h-3 w-3 animate-spin rounded-full border border-blue-400/30 border-t-blue-400" />
                    実行中...
                  </>
                ) : (
                  <>
                    <span className="text-xs">{"\u25B6"}</span>
                    実行
                  </>
                )}
              </button>

              <div className="flex items-center gap-2">
                <span className="text-[10px] text-white/30">
                  {allScriptSchedulersEnabled ? "自動ON" : "自動OFF"}
                </span>
                <button
                  onClick={() => {
                    for (const name of scriptSchedulers) {
                      onSchedulerToggle(
                        name,
                        allScriptSchedulersEnabled ? "ENABLED" : "PAUSED",
                      );
                    }
                  }}
                  disabled={isTogglingAny}
                  className={`relative h-5 w-9 rounded-full transition-colors ${
                    allScriptSchedulersEnabled ? "bg-emerald-600" : "bg-white/10"
                  } ${isTogglingAny ? "opacity-50" : ""}`}
                >
                  <span
                    className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-all ${
                      allScriptSchedulersEnabled ? "left-[18px]" : "left-0.5"
                    }`}
                  />
                </button>
              </div>
            </div>
          </div>
        );
      })}
    </section>
  );
}
