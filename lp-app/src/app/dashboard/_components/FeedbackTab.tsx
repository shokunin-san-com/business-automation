"use client";

import { useState, useEffect, useRef } from "react";
import type { ChatMessage } from "../_types/dashboard";

interface FeedbackMemory {
  id: string;
  type: string;
  source: string;
  category: string;
  content: string;
  priority: string;
  createdAt: string;
}

interface FeedbackPerf {
  businessId: string;
  latestScore: number;
  avgScore: number;
  latestPV: number;
  latestCVR: number;
}

export function FeedbackTab() {
  const [feedbackMessages, setFeedbackMessages] = useState<ChatMessage[]>([]);
  const [feedbackInput, setFeedbackInput] = useState("");
  const [feedbackLoading, setFeedbackLoading] = useState(false);
  const [feedbackMemories, setFeedbackMemories] = useState<FeedbackMemory[]>([]);
  const [feedbackPerf, setFeedbackPerf] = useState<FeedbackPerf[]>([]);
  const feedbackEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchFeedbackData();
  }, []);

  useEffect(() => {
    feedbackEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [feedbackMessages]);

  const fetchFeedbackData = async () => {
    try {
      const res = await fetch("/api/feedback");
      if (res.ok) {
        const d = await res.json();
        setFeedbackMemories(d.memories || []);
        setFeedbackPerf(d.performanceSummary || []);
      }
    } catch { /* ignore */ }
  };

  const handleFeedbackSend = async () => {
    if (!feedbackInput.trim() || feedbackLoading) return;

    const userMessage = feedbackInput.trim();
    setFeedbackInput("");
    setFeedbackMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    setFeedbackLoading(true);

    try {
      const res = await fetch("/api/feedback/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMessage }),
      });

      if (!res.ok) {
        setFeedbackMessages((prev) => [
          ...prev,
          { role: "assistant", content: "エラーが発生しました。" },
        ]);
        return;
      }

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let assistantContent = "";

      setFeedbackMessages((prev) => [...prev, { role: "assistant", content: "" }]);

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split("\n");

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              const payload = line.slice(6);
              if (payload === "[DONE]") break;
              try {
                const parsed = JSON.parse(payload);
                if (parsed.text) {
                  assistantContent += parsed.text;
                  setFeedbackMessages((prev) => {
                    const updated = [...prev];
                    updated[updated.length - 1] = {
                      role: "assistant",
                      content: assistantContent,
                    };
                    return updated;
                  });
                }
                if (parsed.directive_saved) {
                  setTimeout(fetchFeedbackData, 500);
                }
              } catch { /* partial JSON */ }
            }
          }
        }
      }
    } catch (err) {
      console.error("Feedback chat error:", err);
      setFeedbackMessages((prev) => [
        ...prev,
        { role: "assistant", content: "通信エラーが発生しました。" },
      ]);
    } finally {
      setFeedbackLoading(false);
    }
  };

  const handleSupersede = async (memoryId: string) => {
    try {
      await fetch(`/api/feedback?id=${memoryId}`, { method: "DELETE" });
      await fetchFeedbackData();
    } catch (err) {
      console.error("Supersede error:", err);
    }
  };

  return (
    <div className="space-y-6">
      {/* Performance Summary Cards */}
      {feedbackPerf.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {feedbackPerf.map((p) => (
            <div key={p.businessId} className="rounded-2xl border border-amber-500/10 bg-gradient-to-br from-amber-500/[.06] to-orange-500/[.03] p-4">
              <p className="text-xs font-medium text-amber-300">{p.businessId}</p>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-2xl font-semibold">{p.latestScore}</span>
                <span className="text-[10px] text-white/30">/100 (平均{p.avgScore})</span>
              </div>
              <div className="mt-2 flex gap-3 text-[10px] text-white/40">
                <span>PV {p.latestPV}</span>
                <span>CVR {p.latestCVR}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Learning Memories */}
      <section className="rounded-2xl border border-white/[.06] bg-white/[.02] p-5">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">{"\u{1F4DD}"}</span>
            <h2 className="text-sm font-medium text-white/60">学習メモリ ({feedbackMemories.length})</h2>
          </div>
        </div>
        {feedbackMemories.length === 0 ? (
          <p className="text-center py-4 text-sm text-white/20">まだ学習メモリがありません</p>
        ) : (
          <div className="space-y-2 max-h-[300px] overflow-y-auto">
            {feedbackMemories.map((m) => (
              <div key={m.id} className="flex items-start gap-3 rounded-xl bg-black/30 p-3">
                <span className="mt-0.5 text-sm">
                  {m.source === "human_chat" ? "\u{1F464}" : "\u{1F916}"}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-xs text-white/70">{m.content}</p>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    <span className={`rounded-md px-1.5 py-0.5 text-[9px] border ${
                      m.type === "directive"
                        ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
                        : m.type === "pattern"
                        ? "bg-violet-500/10 text-violet-400 border-violet-500/20"
                        : "bg-blue-500/10 text-blue-400 border-blue-500/20"
                    }`}>
                      {m.type}
                    </span>
                    <span className="rounded-md bg-white/5 px-1.5 py-0.5 text-[9px] text-white/40">{m.category}</span>
                    <span className={`rounded-md px-1.5 py-0.5 text-[9px] ${
                      m.priority === "high" ? "bg-red-500/10 text-red-400" :
                      m.priority === "medium" ? "bg-yellow-500/10 text-yellow-400" :
                      "bg-white/5 text-white/30"
                    }`}>
                      {m.priority}
                    </span>
                  </div>
                </div>
                <button
                  onClick={() => handleSupersede(m.id)}
                  className="shrink-0 rounded-lg bg-white/5 px-2 py-1 text-[10px] text-white/30 hover:bg-red-500/10 hover:text-red-400 transition-colors"
                  title="無効化"
                >
                  {"\u2716"}
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Feedback Chat UI */}
      <section className="rounded-2xl border border-amber-500/10 bg-white/[.02] p-5">
        <div className="mb-3 flex items-center gap-2">
          <span className="text-lg">{"\u{1F4AC}"}</span>
          <h2 className="text-sm font-medium text-amber-300">運用フィードバック</h2>
        </div>

        <div className="mb-4 max-h-[400px] overflow-y-auto rounded-xl bg-black/30 p-4 space-y-4">
          {feedbackMessages.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-sm text-white/20">パフォーマンスについて質問したり、方針を指示したり</p>
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                {[
                  "直近のLP成果を教えて",
                  "SNSはカジュアルなトーンで",
                  "フォーム営業の改善点は？",
                  "今後の戦略を提案して",
                ].map((q) => (
                  <button
                    key={q}
                    onClick={() => setFeedbackInput(q)}
                    className="rounded-lg bg-amber-500/5 px-3 py-1.5 text-[11px] text-amber-400/60 hover:bg-amber-500/10 hover:text-amber-400 transition-colors border border-amber-500/10"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            feedbackMessages.map((msg, i) => (
              <div
                key={i}
                className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[85%] rounded-xl px-4 py-2.5 text-xs leading-relaxed ${
                    msg.role === "user"
                      ? "bg-amber-600/20 text-amber-200 border border-amber-500/20"
                      : "bg-white/5 text-white/70 border border-white/[.06]"
                  }`}
                >
                  <div className="whitespace-pre-wrap">{msg.content}</div>
                </div>
              </div>
            ))
          )}
          {feedbackLoading && feedbackMessages[feedbackMessages.length - 1]?.content === "" && (
            <div className="flex justify-start">
              <div className="rounded-xl bg-white/5 px-4 py-2.5 border border-white/[.06]">
                <div className="flex gap-1">
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-400/30 animate-bounce" />
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-400/30 animate-bounce [animation-delay:150ms]" />
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-400/30 animate-bounce [animation-delay:300ms]" />
                </div>
              </div>
            </div>
          )}
          <div ref={feedbackEndRef} />
        </div>

        <div className="flex gap-2">
          <input
            type="text"
            value={feedbackInput}
            onChange={(e) => setFeedbackInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleFeedbackSend();
              }
            }}
            placeholder="パフォーマンスについて質問、または方針を指示..."
            className="flex-1 rounded-xl border border-amber-500/20 bg-white/5 px-4 py-2.5 text-xs text-white outline-none focus:border-amber-500/50 placeholder:text-white/20 transition-colors"
            disabled={feedbackLoading}
          />
          <button
            onClick={handleFeedbackSend}
            disabled={feedbackLoading || !feedbackInput.trim()}
            className="shrink-0 rounded-xl bg-amber-600 px-4 py-2.5 text-xs font-medium text-white transition-all hover:bg-amber-500 disabled:opacity-40"
          >
            {feedbackLoading ? "..." : "送信"}
          </button>
        </div>
      </section>
    </div>
  );
}
