"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";

interface PostRow {
  id: string;
  title: string;
  slug: string;
  status: string;
  category: string;
  published_at: string | null;
  updated_at: string;
}

type StatusFilter = "all" | "published" | "draft";

export default function PostsListPage() {
  const [posts, setPosts] = useState<PostRow[]>([]);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const supabase = createClient();
    let query = supabase
      .from("posts")
      .select("id, title, slug, status, category, published_at, updated_at")
      .order("updated_at", { ascending: false });

    if (filter !== "all") {
      query = query.eq("status", filter);
    }

    query.then(({ data }) => {
      setPosts(data || []);
      setLoading(false);
    });
  }, [filter]);

  const handleDelete = async (id: string, title: string) => {
    if (!confirm(`「${title}」を削除しますか？`)) return;

    const supabase = createClient();
    await supabase.from("posts").delete().eq("id", id);
    setPosts((prev) => prev.filter((p) => p.id !== id));
  };

  const handleToggleStatus = async (id: string, currentStatus: string) => {
    const newStatus = currentStatus === "published" ? "draft" : "published";
    const supabase = createClient();

    const updates: Record<string, unknown> = { status: newStatus };
    if (newStatus === "published") {
      updates.published_at = new Date().toISOString();
    }

    await supabase.from("posts").update(updates).eq("id", id);
    setPosts((prev) =>
      prev.map((p) =>
        p.id === id
          ? { ...p, status: newStatus, published_at: newStatus === "published" ? new Date().toISOString() : p.published_at }
          : p,
      ),
    );
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">記事管理</h1>
        <Link
          href="/blog/admin/posts/new"
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-bold text-white hover:bg-blue-700"
        >
          + 新規記事
        </Link>
      </div>

      {/* Status filter */}
      <div className="flex gap-2 mb-4">
        {(["all", "published", "draft"] as StatusFilter[]).map((f) => (
          <button
            key={f}
            onClick={() => { setFilter(f); setLoading(true); }}
            className={`rounded-full px-4 py-1.5 text-sm font-medium transition ${
              filter === f
                ? "bg-blue-600 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            {f === "all" ? "すべて" : f === "published" ? "公開" : "下書き"}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="text-gray-400 py-8 text-center">読み込み中...</p>
      ) : posts.length === 0 ? (
        <p className="text-gray-400 py-8 text-center">記事がありません</p>
      ) : (
        <div className="rounded-lg border bg-white overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-gray-500">
                  タイトル
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-500 w-24">
                  状態
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-500 w-28">
                  カテゴリ
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-500 w-32">
                  更新日
                </th>
                <th className="text-right px-4 py-3 font-medium text-gray-500 w-32">
                  操作
                </th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {posts.map((post) => (
                <tr key={post.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <Link
                      href={`/blog/admin/posts/${post.id}`}
                      className="text-blue-600 hover:underline font-medium line-clamp-1"
                    >
                      {post.title}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                        post.status === "published"
                          ? "bg-green-100 text-green-700"
                          : "bg-yellow-100 text-yellow-700"
                      }`}
                    >
                      {post.status === "published" ? "公開" : "下書き"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {post.category}
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-xs">
                    {new Date(post.updated_at).toLocaleDateString("ja-JP")}
                  </td>
                  <td className="px-4 py-3 text-right space-x-2">
                    <button
                      onClick={() => handleToggleStatus(post.id, post.status)}
                      className="text-xs text-blue-600 hover:underline"
                    >
                      {post.status === "published" ? "下書きに" : "公開"}
                    </button>
                    <button
                      onClick={() => handleDelete(post.id, post.title)}
                      className="text-xs text-red-500 hover:underline"
                    >
                      削除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
