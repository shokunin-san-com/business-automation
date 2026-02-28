"use client";

import { useRef } from "react";

interface Props {
  logs: string[];
}

export function LogsTab({ logs }: Props) {
  const logEndRef = useRef<HTMLDivElement>(null);

  return (
    <section className="rounded-2xl border border-white/[.06] bg-white/[.02] p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-medium text-white/60">実行ログ</h2>
        <span className="text-[10px] text-white/20">{logs.length}件</span>
      </div>
      <div className="max-h-[500px] overflow-y-auto rounded-xl bg-black/50 p-4 font-mono text-[11px] leading-5">
        {logs.length === 0 ? (
          <p className="text-white/20">ログはまだありません</p>
        ) : (
          logs.map((line, i) => (
            <div
              key={i}
              className={`${
                line.includes("ERROR") || line.includes("AUTO-PAUSE") || line.includes("CRITICAL")
                  ? "text-red-400"
                  : line.includes("WARNING") || line.includes("BLOCKED")
                  ? "text-amber-400"
                  : line.includes("success") || line.includes("complete") || line.includes("\u2705")
                  ? "text-emerald-400"
                  : line.includes("manual") || line.includes("triggered")
                  ? "text-blue-400"
                  : line.includes("INFO")
                  ? "text-white/35"
                  : "text-white/25"
              }`}
            >
              {line}
            </div>
          ))
        )}
        <div ref={logEndRef} />
      </div>
    </section>
  );
}
