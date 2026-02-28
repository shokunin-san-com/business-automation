"use client";

import { useEffect, useCallback } from "react";
import { cronToJapanese, SCHEDULE_PRESETS } from "./PipelineCards";

interface Props {
  target: { schedulerName: string; scriptLabel: string; currentCron: string } | null;
  cron: string;
  setCron: (v: string) => void;
  saving: boolean;
  onSave: () => void;
  onClose: () => void;
}

export function ScheduleEditModal({ target, cron, setCron, saving, onSave, onClose }: Props) {
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === "Escape") onClose();
  }, [onClose]);

  useEffect(() => {
    if (target) {
      document.addEventListener("keydown", handleKeyDown);
      return () => document.removeEventListener("keydown", handleKeyDown);
    }
  }, [target, handleKeyDown]);

  if (!target) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-white/10 bg-[#12121a] p-6 shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-label={`スケジュール編集 - ${target.scriptLabel}`}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">
            スケジュール編集 — {target.scriptLabel}
          </h3>
          <button
            onClick={onClose}
            className="text-white/30 hover:text-white/60 text-lg"
          >
            {"\u2715"}
          </button>
        </div>

        <div className="mb-4">
          <p className="mb-1 text-[10px] text-white/30">現在のスケジュール</p>
          <p className="text-xs text-white/60">
            {target.currentCron
              ? `${cronToJapanese(target.currentCron)} (${target.currentCron})`
              : "未設定"}
          </p>
        </div>

        <div className="mb-4">
          <p className="mb-2 text-[10px] text-white/30">プリセット</p>
          <div className="flex flex-wrap gap-2">
            {SCHEDULE_PRESETS.map((preset) => (
              <button
                key={preset.cron}
                onClick={() => setCron(preset.cron)}
                className={`rounded-lg px-3 py-1.5 text-[11px] border transition-all ${
                  cron === preset.cron
                    ? "bg-blue-600/20 text-blue-400 border-blue-500/30"
                    : "bg-white/5 text-white/40 border-white/10 hover:bg-white/10"
                }`}
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>

        <div className="mb-5">
          <p className="mb-1 text-[10px] text-white/30">カスタムcron式 (分 時 日 月 曜日)</p>
          <input
            type="text"
            value={cron}
            onChange={(e) => setCron(e.target.value)}
            placeholder="0 9 * * *"
            className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-xs text-white font-mono outline-none focus:border-blue-500/50 placeholder:text-white/20"
          />
          {cron && (
            <p className="mt-1 text-[10px] text-blue-400/60">
              {cronToJapanese(cron)}
            </p>
          )}
        </div>

        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 rounded-xl bg-white/5 py-2.5 text-xs font-medium text-white/60 hover:bg-white/10 transition-colors"
          >
            キャンセル
          </button>
          <button
            onClick={onSave}
            disabled={saving || !cron.trim()}
            className="flex-1 rounded-xl bg-blue-600 py-2.5 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-40 transition-colors"
          >
            {saving ? "保存中..." : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}
