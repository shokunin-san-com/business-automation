"use client";

import { useEffect, useState, useCallback } from "react";
import AppShell from "../../components/AppShell";

interface BusinessIdea {
  id: string;
  name: string;
  category: string;
  description: string;
  target_audience: string;
  status: string;
  created_at: string;
  has_lp: boolean;
}

interface IdeasData {
  active: BusinessIdea[];
  draft: BusinessIdea[];
  archived: BusinessIdea[];
  totalCount: number;
  activeCount: number;
}

function formatDate(dateStr: string): string {
  if (!dateStr) return "";
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString("ja-JP", { year: "numeric", month: "2-digit", day: "2-digit" });
  } catch {
    return dateStr;
  }
}

const STATUS_STYLES: Record<string, { dot: string; text: string; label: string }> = {
  active: { dot: "bg-emerald-400", text: "text-emerald-400", label: "アクティブ" },
  draft: { dot: "bg-amber-400", text: "text-amber-400", label: "承認待ち" },
  archived: { dot: "bg-white/20", text: "text-white/30", label: "アーカイブ" },
};

/* ------------------------------------------------------------------ */
/*  Detail Modal                                                       */
/* ------------------------------------------------------------------ */
function DetailModal({
  idea,
  onClose,
  onAction,
  acting,
}: {
  idea: BusinessIdea;
  onClose: () => void;
  onAction: (id: string, action: string) => void;
  acting: boolean;
}) {
  const st = STATUS_STYLES[idea.status] || STATUS_STYLES.draft;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="mx-4 w-full max-w-lg rounded-2xl border border-white/[.08] bg-[#12121a] p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-base font-semibold leading-snug">{idea.name}</h2>
          <button
            onClick={onClose}
            className="shrink-0 rounded-lg p-1.5 text-white/30 transition-colors hover:bg-white/5 hover:text-white/60"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="mt-3 flex items-center gap-1.5">
          <div className={`h-2 w-2 rounded-full ${st.dot}`} />
          <span className={`text-xs ${st.text}`}>{st.label}</span>
        </div>

        <div className="mt-3 flex flex-wrap gap-1.5">
          {idea.category && (
            <span className="rounded-md bg-white/5 px-2 py-0.5 text-[11px] text-white/50">
              {idea.category}
            </span>
          )}
          {idea.target_audience && (
            <span className="rounded-md bg-white/5 px-2 py-0.5 text-[11px] text-white/50">
              {idea.target_audience}
            </span>
          )}
        </div>

        {idea.description && (
          <div className="mt-4 max-h-60 overflow-y-auto rounded-xl bg-white/[.03] p-4">
            <p className="text-[11px] font-medium text-white/30 mb-2">概要</p>
            <p className="text-xs leading-relaxed text-white/60 whitespace-pre-wrap">
              {idea.description}
            </p>
          </div>
        )}

        <div className="mt-4 flex items-center gap-4 text-[10px] text-white/20">
          {idea.created_at && <span>作成日: {formatDate(idea.created_at)}</span>}
          <span>ID: {idea.id}</span>
        </div>

        <div className="mt-6 flex items-center gap-2 border-t border-white/[.06] pt-4">
          {idea.has_lp && (
            <a
              href={`/lp/${idea.id}`}
              className="rounded-lg border border-blue-500/20 bg-blue-600/20 px-3 py-1.5 text-[11px] font-medium text-blue-400 no-underline transition-colors hover:bg-blue-600/30"
            >
              LP を見る
            </a>
          )}
          <div className="flex-1" />
          {idea.status === "draft" && (
            <>
              <button
                disabled={acting}
                onClick={() => onAction(idea.id, "approve")}
                className="rounded-lg bg-emerald-600/20 border border-emerald-500/20 px-3 py-1.5 text-[11px] font-medium text-emerald-400 transition-colors hover:bg-emerald-600/30 disabled:opacity-40"
              >
                {acting ? "..." : "承認する"}
              </button>
              <button
                disabled={acting}
                onClick={() => onAction(idea.id, "reject")}
                className="rounded-lg bg-red-600/20 border border-red-500/20 px-3 py-1.5 text-[11px] font-medium text-red-400 transition-colors hover:bg-red-600/30 disabled:opacity-40"
              >
                {acting ? "..." : "却下する"}
              </button>
            </>
          )}
          {idea.status === "active" && (
            <button
              disabled={acting}
              onClick={() => onAction(idea.id, "archive")}
              className="rounded-lg bg-white/5 border border-white/10 px-3 py-1.5 text-[11px] font-medium text-white/40 transition-colors hover:bg-white/10 disabled:opacity-40"
            >
              {acting ? "..." : "アーカイブ"}
            </button>
          )}
          {idea.status === "archived" && (
            <button
              disabled={acting}
              onClick={() => onAction(idea.id, "restore")}
              className="rounded-lg bg-emerald-600/20 border border-emerald-500/20 px-3 py-1.5 text-[11px] font-medium text-emerald-400 transition-colors hover:bg-emerald-600/30 disabled:opacity-40"
            >
              {acting ? "..." : "復元する"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Idea Card                                                          */
/* ------------------------------------------------------------------ */
function IdeaCard({
  idea,
  onOpen,
  onAction,
  acting,
}: {
  idea: BusinessIdea;
  onOpen: (idea: BusinessIdea) => void;
  onAction: (id: string, action: string) => void;
  acting: boolean;
}) {
  const st = STATUS_STYLES[idea.status] || STATUS_STYLES.draft;
  return (
    <div
      className="cursor-pointer rounded-2xl border border-white/[.06] bg-white/[.02] p-5 transition-all hover:border-white/[.12] hover:bg-white/[.04]"
      onClick={() => onOpen(idea)}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-medium leading-snug">{idea.name}</h3>
        <div className="flex shrink-0 items-center gap-1.5">
          <div className={`h-2 w-2 rounded-full ${st.dot}`} />
          <span className={`text-[10px] ${st.text}`}>{st.label}</span>
        </div>
      </div>

      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {idea.category && (
          <span className="rounded-md bg-white/5 px-2 py-0.5 text-[10px] text-white/50">
            {idea.category}
          </span>
        )}
        {idea.target_audience && (
          <span className="rounded-md bg-white/5 px-2 py-0.5 text-[10px] text-white/50">
            {idea.target_audience}
          </span>
        )}
      </div>

      {idea.description && (
        <p className="mt-3 text-xs leading-relaxed text-white/40 line-clamp-2">
          {idea.description}
        </p>
      )}

      <div className="mt-4 flex items-center justify-between" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2">
          {idea.has_lp && (
            <a
              href={`/lp/${idea.id}`}
              className="rounded-lg border border-blue-500/20 bg-blue-600/20 px-2.5 py-1 text-[10px] font-medium text-blue-400 no-underline transition-colors hover:bg-blue-600/30"
            >
              LP
            </a>
          )}
          {idea.status === "draft" && (
            <>
              <button
                disabled={acting}
                onClick={() => onAction(idea.id, "approve")}
                className="rounded-lg bg-emerald-600/20 border border-emerald-500/20 px-2.5 py-1 text-[10px] font-medium text-emerald-400 transition-colors hover:bg-emerald-600/30 disabled:opacity-40"
              >
                承認
              </button>
              <button
                disabled={acting}
                onClick={() => onAction(idea.id, "reject")}
                className="rounded-lg bg-red-600/20 border border-red-500/20 px-2.5 py-1 text-[10px] font-medium text-red-400 transition-colors hover:bg-red-600/30 disabled:opacity-40"
              >
                却下
              </button>
            </>
          )}
          {idea.status === "active" && (
            <button
              disabled={acting}
              onClick={() => onAction(idea.id, "archive")}
              className="rounded-lg bg-white/5 border border-white/10 px-2.5 py-1 text-[10px] font-medium text-white/30 transition-colors hover:bg-white/10 disabled:opacity-40"
            >
              アーカイブ
            </button>
          )}
          {idea.status === "archived" && (
            <button
              disabled={acting}
              onClick={() => onAction(idea.id, "restore")}
              className="rounded-lg bg-emerald-600/20 border border-emerald-500/20 px-2.5 py-1 text-[10px] font-medium text-emerald-400 transition-colors hover:bg-emerald-600/30 disabled:opacity-40"
            >
              復元
            </button>
          )}
        </div>
        {idea.created_at && (
          <span className="text-[10px] text-white/20">{formatDate(idea.created_at)}</span>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Summary Card                                                       */
/* ------------------------------------------------------------------ */
function SummaryCard({ label, count, accent }: { label: string; count: number; accent: string }) {
  const colors: Record<string, string> = {
    emerald: "from-emerald-500/20 to-emerald-500/5 border-emerald-500/20",
    amber: "from-amber-500/20 to-amber-500/5 border-amber-500/20",
    gray: "from-white/10 to-white/[.02] border-white/10",
  };
  const textColors: Record<string, string> = {
    emerald: "text-emerald-400",
    amber: "text-amber-400",
    gray: "text-white/40",
  };
  return (
    <div className={`rounded-2xl border bg-gradient-to-b ${colors[accent]} p-5`}>
      <p className="text-xs text-white/40">{label}</p>
      <p className={`mt-1 text-2xl font-bold ${textColors[accent]}`}>{count}</p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Page                                                          */
/* ------------------------------------------------------------------ */
export default function IdeasPage() {
  const [data, setData] = useState<IdeasData | null>(null);
  const [loading, setLoading] = useState(true);
  const [showArchived, setShowArchived] = useState(false);
  const [selectedIdea, setSelectedIdea] = useState<BusinessIdea | null>(null);
  const [acting, setActing] = useState(false);

  const fetchData = useCallback(() => {
    fetch("/api/ideas")
      .then((r) => r.json())
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleAction = useCallback(
    async (ideaId: string, action: string) => {
      setActing(true);
      try {
        const apiAction = action === "approve" || action === "restore" ? "approve" : "reject";
        const res = await fetch("/api/slack/approve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ idea_id: ideaId, action: apiAction, user: "ideas_page" }),
        });
        if (res.ok) {
          setSelectedIdea(null);
          fetchData();
        }
      } catch {
        // best effort
      } finally {
        setActing(false);
      }
    },
    [fetchData]
  );

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl px-6 py-8">
        <div className="mb-8">
          <h1 className="text-lg font-semibold">事業案一覧</h1>
          <p className="mt-1 text-xs text-white/30">
            パイプラインで生成・管理されている事業案
          </p>
        </div>

        {loading ? (
          <div className="flex h-40 items-center justify-center">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-blue-500" />
          </div>
        ) : !data || data.totalCount === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-2xl border border-white/[.06] bg-white/[.02] py-20">
            <svg className="h-10 w-10 text-white/10" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 18v-5.25m0 0a6.01 6.01 0 001.5-.189m-1.5.189a6.01 6.01 0 01-1.5-.189m3.75 7.478a12.06 12.06 0 01-4.5 0m3.75 2.383a14.406 14.406 0 01-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 10-7.517 0c.85.493 1.509 1.333 1.509 2.316V18" />
            </svg>
            <p className="mt-4 text-sm text-white/30">事業案がまだありません</p>
            <p className="mt-1 text-[11px] text-white/15">事業案生成パイプラインを実行してください</p>
          </div>
        ) : (
          <>
            <div className="mb-8 grid gap-3 sm:grid-cols-3">
              <SummaryCard label="アクティブ" count={data.active.length} accent="emerald" />
              <SummaryCard label="承認待ち" count={data.draft.length} accent="amber" />
              <SummaryCard label="アーカイブ" count={data.archived.length} accent="gray" />
            </div>

            {data.draft.length > 0 && (
              <section className="mb-8">
                <h2 className="mb-4 flex items-center gap-2 text-sm font-medium">
                  <div className="h-2 w-2 rounded-full bg-amber-400" />
                  承認待ち
                  <span className="text-[10px] text-white/30">({data.draft.length})</span>
                </h2>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {data.draft.map((idea) => (
                    <IdeaCard key={idea.id} idea={idea} onOpen={setSelectedIdea} onAction={handleAction} acting={acting} />
                  ))}
                </div>
              </section>
            )}

            {data.active.length > 0 && (
              <section className="mb-8">
                <h2 className="mb-4 flex items-center gap-2 text-sm font-medium">
                  <div className="h-2 w-2 rounded-full bg-emerald-400" />
                  アクティブな事業案
                  <span className="text-[10px] text-white/30">({data.active.length})</span>
                </h2>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {data.active.map((idea) => (
                    <IdeaCard key={idea.id} idea={idea} onOpen={setSelectedIdea} onAction={handleAction} acting={acting} />
                  ))}
                </div>
              </section>
            )}

            {data.archived.length > 0 && (
              <section className="mb-8">
                <button
                  onClick={() => setShowArchived(!showArchived)}
                  className="mb-4 flex items-center gap-2 text-sm font-medium text-white/40 transition-colors hover:text-white/60"
                >
                  <svg
                    className={`h-3 w-3 transition-transform ${showArchived ? "rotate-90" : ""}`}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                  </svg>
                  アーカイブ
                  <span className="text-[10px] text-white/20">({data.archived.length})</span>
                </button>
                {showArchived && (
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {data.archived.map((idea) => (
                      <IdeaCard key={idea.id} idea={idea} onOpen={setSelectedIdea} onAction={handleAction} acting={acting} />
                    ))}
                  </div>
                )}
              </section>
            )}
          </>
        )}
      </div>

      {selectedIdea && (
        <DetailModal
          idea={selectedIdea}
          onClose={() => setSelectedIdea(null)}
          onAction={handleAction}
          acting={acting}
        />
      )}
    </AppShell>
  );
}
