"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

interface PostData {
  id: string;
  title: string;
  slug: string;
  status: string;
  body_html: string;
  excerpt: string;
  category: string;
  tags: string[];
  meta_description: string;
  og_title: string;
  og_description: string;
  business_id: string;
  media_id: string;
  published_at: string | null;
}

export default function PostEditPage() {
  const router = useRouter();
  const params = useParams();
  const id = params.id as string;
  const isNew = id === "new";

  const [post, setPost] = useState<PostData>({
    id: "",
    title: "",
    slug: "",
    status: "draft",
    body_html: "",
    excerpt: "",
    category: "",
    tags: [],
    meta_description: "",
    og_title: "",
    og_description: "",
    business_id: "",
    media_id: "shokunin-san",
    published_at: null,
  });
  const [tagsInput, setTagsInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(!isNew);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (isNew) return;
    const supabase = createClient();
    supabase
      .from("posts")
      .select("*")
      .eq("id", id)
      .single()
      .then(({ data }) => {
        if (data) {
          setPost(data as PostData);
          setTagsInput((data.tags || []).join(", "));
        }
        setLoading(false);
      });
  }, [id, isNew]);

  const handleSave = async (publishNow = false) => {
    setSaving(true);
    setMessage("");

    const supabase = createClient();
    const tags = tagsInput
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);

    const payload = {
      title: post.title,
      slug: post.slug || post.title.replace(/\s+/g, "-").toLowerCase(),
      status: publishNow ? "published" : post.status,
      body_html: post.body_html,
      excerpt: post.excerpt,
      category: post.category,
      tags,
      meta_description: post.meta_description,
      og_title: post.og_title || post.title,
      og_description: post.og_description || post.meta_description,
      business_id: post.business_id,
      media_id: post.media_id || "shokunin-san",
      published_at:
        publishNow && !post.published_at
          ? new Date().toISOString()
          : post.published_at,
    };

    if (isNew) {
      const { error } = await supabase.from("posts").insert(payload);
      if (error) {
        setMessage(`エラー: ${error.message}`);
      } else {
        setMessage("作成しました");
        router.push("/blog/admin/posts");
      }
    } else {
      const { error } = await supabase
        .from("posts")
        .update(payload)
        .eq("id", id);
      if (error) {
        setMessage(`エラー: ${error.message}`);
      } else {
        setMessage("保存しました");
      }
    }
    setSaving(false);
  };

  if (loading)
    return <p className="text-gray-400 py-8 text-center">読み込み中...</p>;

  return (
    <div className="max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">
          {isNew ? "新規記事" : "記事編集"}
        </h1>
        <div className="flex gap-2">
          <button
            onClick={() => handleSave(false)}
            disabled={saving}
            className="rounded-lg border px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            下書き保存
          </button>
          <button
            onClick={() => handleSave(true)}
            disabled={saving}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-bold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            公開
          </button>
        </div>
      </div>

      {message && (
        <div
          className={`mb-4 rounded-lg p-3 text-sm ${
            message.startsWith("エラー")
              ? "bg-red-50 text-red-700"
              : "bg-green-50 text-green-700"
          }`}
        >
          {message}
        </div>
      )}

      <div className="space-y-4">
        {/* Title */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            タイトル
          </label>
          <input
            type="text"
            value={post.title}
            onChange={(e) => setPost({ ...post, title: e.target.value })}
            className="w-full rounded-lg border px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            placeholder="記事タイトル"
          />
        </div>

        {/* Slug */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            スラッグ
          </label>
          <input
            type="text"
            value={post.slug}
            onChange={(e) => setPost({ ...post, slug: e.target.value })}
            className="w-full rounded-lg border px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            placeholder="url-slug"
          />
        </div>

        {/* Category + Business ID row */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              カテゴリ
            </label>
            <input
              type="text"
              value={post.category}
              onChange={(e) => setPost({ ...post, category: e.target.value })}
              className="w-full rounded-lg border px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              事業ID
            </label>
            <input
              type="text"
              value={post.business_id}
              onChange={(e) =>
                setPost({ ...post, business_id: e.target.value })
              }
              className="w-full rounded-lg border px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              placeholder="run_id or business identifier"
            />
          </div>
        </div>

        {/* Tags */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            タグ（カンマ区切り）
          </label>
          <input
            type="text"
            value={tagsInput}
            onChange={(e) => setTagsInput(e.target.value)}
            className="w-full rounded-lg border px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            placeholder="塗装, リフォーム, DX"
          />
        </div>

        {/* Excerpt */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            概要（excerpt）
          </label>
          <textarea
            value={post.excerpt}
            onChange={(e) => setPost({ ...post, excerpt: e.target.value })}
            rows={2}
            className="w-full rounded-lg border px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>

        {/* Meta description */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            メタディスクリプション
          </label>
          <textarea
            value={post.meta_description}
            onChange={(e) =>
              setPost({ ...post, meta_description: e.target.value })
            }
            rows={2}
            className="w-full rounded-lg border px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>

        {/* Body HTML */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            本文（HTML）
          </label>
          <textarea
            value={post.body_html}
            onChange={(e) => setPost({ ...post, body_html: e.target.value })}
            rows={20}
            className="w-full rounded-lg border px-3 py-2 text-sm font-mono focus:border-blue-500 focus:outline-none"
          />
        </div>

        {/* Preview */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            プレビュー
          </label>
          <div
            className="rounded-lg border bg-white p-6 prose prose-sm max-w-none"
            dangerouslySetInnerHTML={{ __html: post.body_html }}
          />
        </div>
      </div>
    </div>
  );
}
