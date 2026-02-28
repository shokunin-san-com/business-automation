"use client";

import { useState, useEffect, useRef } from "react";
import type { KnowledgeDoc, ChatMessage } from "../_types/dashboard";

function formatTime(iso: string): string {
  if (!iso) return "\u2014";
  const d = new Date(iso);
  return d.toLocaleString("ja-JP", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function KnowledgeTab() {
  const [knowledgeDocs, setKnowledgeDocs] = useState<KnowledgeDoc[]>([]);
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetchKnowledge();
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  const fetchKnowledge = async () => {
    setKnowledgeLoading(true);
    try {
      const res = await fetch("/api/knowledge");
      if (res.ok) {
        const d = await res.json();
        setKnowledgeDocs(d.documents || []);
      }
    } catch { /* ignore */ }
    finally { setKnowledgeLoading(false); }
  };

  const handleFileUpload = async (file: File) => {
    const MAX_SIZE_MB = 4;
    if (file.size > MAX_SIZE_MB * 1024 * 1024) {
      alert(
        `ファイルが大きすぎます（${(file.size / 1024 / 1024).toFixed(1)}MB）。\n\n` +
        `Web UIは${MAX_SIZE_MB}MBまで対応です。\n` +
        `大きいファイルはターミナルからアップロードしてください:\n\n` +
        `  python3 scripts/upload_knowledge.py references/${file.name}`
      );
      return;
    }

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch("/api/knowledge", {
        method: "POST",
        body: formData,
      });
      const result = await res.json();
      if (res.ok) {
        await fetchKnowledge();
      } else {
        console.error("Upload failed:", result);
        alert(result.error || "アップロードに失敗しました");
      }
    } catch (err) {
      console.error("Upload error:", err);
      alert("アップロード中にエラーが発生しました。ファイルが大きすぎるか、接続がタイムアウトした可能性があります。\n\n大きいファイルはターミナルから:\npython3 scripts/upload_knowledge.py references/" + file.name);
    } finally {
      setUploading(false);
    }
  };

  const handleChatSend = async () => {
    if (!chatInput.trim() || chatLoading) return;

    const userMessage = chatInput.trim();
    setChatInput("");
    setChatMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    setChatLoading(true);

    try {
      const res = await fetch("/api/knowledge/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMessage }),
      });

      if (!res.ok) {
        setChatMessages((prev) => [
          ...prev,
          { role: "assistant", content: "エラーが発生しました。もう一度お試しください。" },
        ]);
        return;
      }

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let assistantContent = "";

      setChatMessages((prev) => [...prev, { role: "assistant", content: "" }]);

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
                  setChatMessages((prev) => {
                    const updated = [...prev];
                    updated[updated.length - 1] = {
                      role: "assistant",
                      content: assistantContent,
                    };
                    return updated;
                  });
                }
              } catch { /* partial JSON */ }
            }
          }
        }
      }
    } catch (err) {
      console.error("Chat error:", err);
      setChatMessages((prev) => [
        ...prev,
        { role: "assistant", content: "通信エラーが発生しました。" },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Upload Area */}
      <section className="rounded-2xl border border-dashed border-violet-500/30 bg-gradient-to-r from-violet-500/[.04] to-purple-500/[.04] p-6">
        <div
          className="flex flex-col items-center justify-center gap-3 cursor-pointer"
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
          onDrop={(e) => {
            e.preventDefault();
            e.stopPropagation();
            const file = e.dataTransfer.files?.[0];
            const supportedExts = [".pdf", ".csv", ".xlsx", ".xls", ".png", ".jpg", ".jpeg", ".webp"];
            if (file && supportedExts.some(ext => file.name.toLowerCase().endsWith(ext))) handleFileUpload(file);
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.csv,.xlsx,.xls,.png,.jpg,.jpeg,.webp"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFileUpload(file);
            }}
          />
          {uploading ? (
            <>
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-violet-400/30 border-t-violet-400" />
              <p className="text-sm text-violet-300">ファイルを分析中...</p>
              <p className="text-[10px] text-white/30">AIでコンテンツを分析しています</p>
            </>
          ) : (
            <>
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-violet-500/10">
                <span className="text-2xl">{"\u{1F4CE}"}</span>
              </div>
              <p className="text-sm font-medium text-violet-300">ファイルをアップロード</p>
              <p className="text-[10px] text-white/30">PDF, CSV, Excel, 画像に対応（最大 4MB）</p>
              <p className="text-[9px] text-white/20 mt-1">4MB以上のファイルはターミナルから: python3 scripts/upload_knowledge.py references/ファイル名</p>
            </>
          )}
        </div>
      </section>

      {/* Document List */}
      <section>
        <h2 className="mb-3 text-sm font-medium text-white/60">
          登録済みドキュメント ({knowledgeDocs.length})
        </h2>
        {knowledgeLoading ? (
          <div className="flex h-20 items-center justify-center">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-white/20 border-t-violet-400" />
          </div>
        ) : knowledgeDocs.length === 0 ? (
          <div className="rounded-2xl border border-white/[.06] bg-white/[.02] p-8 text-center">
            <p className="text-sm text-white/30">まだドキュメントが登録されていません</p>
            <p className="mt-1 text-[10px] text-white/15">上のアップロードでファイルを追加してください</p>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {knowledgeDocs.map((doc) => (
              <div
                key={doc.id}
                className="rounded-2xl border border-white/[.06] bg-white/[.02] p-5 transition-all hover:border-white/[.12]"
              >
                <div className="flex items-start gap-3">
                  <span className="text-2xl">{"\u{1F4D6}"}</span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{doc.title}</p>
                    <p className="mt-1 text-xs text-white/40 line-clamp-3">{doc.summary}</p>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      <span className="rounded-md bg-violet-500/10 px-2 py-0.5 text-[10px] text-violet-400 border border-violet-500/20">
                        {doc.chapterCount} 章
                      </span>
                      {doc.keyFrameworks.slice(0, 3).map((fw) => (
                        <span key={fw} className="rounded-md bg-white/5 px-2 py-0.5 text-[10px] text-white/40">
                          {fw}
                        </span>
                      ))}
                    </div>
                    <p className="mt-2 text-[10px] text-white/20">{formatTime(doc.uploadedAt)}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Chat UI */}
      <section className="rounded-2xl border border-white/[.06] bg-white/[.02] p-5">
        <div className="mb-3 flex items-center gap-2">
          <span className="text-lg">{"\u{1F4AC}"}</span>
          <h2 className="text-sm font-medium text-white/60">知識ベース Q&A</h2>
        </div>

        <div className="mb-4 max-h-[400px] overflow-y-auto rounded-xl bg-black/30 p-4 space-y-4">
          {chatMessages.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-sm text-white/20">書籍の内容について質問してみましょう</p>
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                {["事業検証のフレームワークは？", "MIT 24ステップの概要は？", "TAMの算出方法は？"].map((q) => (
                  <button
                    key={q}
                    onClick={() => { setChatInput(q); }}
                    className="rounded-lg bg-white/5 px-3 py-1.5 text-[11px] text-white/40 hover:bg-white/10 hover:text-white/60 transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            chatMessages.map((msg, i) => (
              <div
                key={i}
                className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[85%] rounded-xl px-4 py-2.5 text-xs leading-relaxed ${
                    msg.role === "user"
                      ? "bg-blue-600/20 text-blue-200 border border-blue-500/20"
                      : "bg-white/5 text-white/70 border border-white/[.06]"
                  }`}
                >
                  <div className="whitespace-pre-wrap">{msg.content}</div>
                </div>
              </div>
            ))
          )}
          {chatLoading && chatMessages[chatMessages.length - 1]?.content === "" && (
            <div className="flex justify-start">
              <div className="rounded-xl bg-white/5 px-4 py-2.5 border border-white/[.06]">
                <div className="flex gap-1">
                  <span className="h-1.5 w-1.5 rounded-full bg-white/30 animate-bounce" />
                  <span className="h-1.5 w-1.5 rounded-full bg-white/30 animate-bounce [animation-delay:150ms]" />
                  <span className="h-1.5 w-1.5 rounded-full bg-white/30 animate-bounce [animation-delay:300ms]" />
                </div>
              </div>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        <div className="flex gap-2">
          <input
            type="text"
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleChatSend();
              }
            }}
            placeholder="書籍の内容について質問..."
            className="flex-1 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-xs text-white outline-none focus:border-violet-500/50 placeholder:text-white/20 transition-colors"
            disabled={chatLoading}
          />
          <button
            onClick={handleChatSend}
            disabled={chatLoading || !chatInput.trim()}
            className="shrink-0 rounded-xl bg-violet-600 px-4 py-2.5 text-xs font-medium text-white transition-all hover:bg-violet-500 disabled:opacity-40"
          >
            {chatLoading ? "..." : "送信"}
          </button>
        </div>
      </section>
    </div>
  );
}
