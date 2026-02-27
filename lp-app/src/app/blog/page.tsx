import type { Metadata } from "next";
import Link from "next/link";
import { getAllArticles } from "@/lib/blog-data";

export const revalidate = 300;

export const metadata: Metadata = {
  title: "ブログ | MarketProbe",
  description:
    "塗装・リフォーム業界のDX、見積もり自動化、業務効率化に関する最新情報をお届けします。",
};

function ArticleCard({
  article,
}: {
  article: {
    slug: string;
    title: string;
    excerpt: string;
    category: string;
    published_at: string;
  };
}) {
  const date = article.published_at
    ? new Date(article.published_at).toLocaleDateString("ja-JP")
    : "";

  return (
    <Link
      href={`/blog/${encodeURIComponent(article.slug)}`}
      className="block rounded-lg border border-gray-200 bg-white p-6 shadow-sm transition hover:shadow-md hover:border-blue-300"
    >
      <div className="mb-2 flex items-center gap-2">
        {article.category && (
          <span className="rounded-full bg-blue-100 px-3 py-0.5 text-xs font-medium text-blue-700">
            {article.category}
          </span>
        )}
        {date && <span className="text-xs text-gray-400">{date}</span>}
      </div>
      <h2 className="mb-2 text-lg font-bold text-gray-900 line-clamp-2">
        {article.title}
      </h2>
      <p className="text-sm text-gray-600 line-clamp-3">{article.excerpt}</p>
    </Link>
  );
}

export default async function BlogPage() {
  const articles = await getAllArticles();

  // Sort by published_at descending
  articles.sort(
    (a, b) =>
      new Date(b.published_at).getTime() - new Date(a.published_at).getTime(),
  );

  return (
    <div className="mx-auto max-w-5xl px-4 py-12">
      <header className="mb-10 text-center">
        <h1 className="text-3xl font-bold text-gray-900">ブログ</h1>
        <p className="mt-2 text-gray-600">
          塗装・リフォーム業界のDX・見積もり自動化に関する最新情報
        </p>
      </header>

      {/* LP Banner */}
      <div className="mb-10 rounded-xl bg-gradient-to-r from-blue-600 to-blue-800 p-6 text-white">
        <h2 className="text-xl font-bold">
          住宅塗装の見積もり、まだ手作業ですか？
        </h2>
        <p className="mt-2 text-blue-100">
          AIが顧客の要望を反映した最適な見積もりを自動生成。成約率アップと業務効率化を同時に実現。
        </p>
        <Link
          href="/lp/%E4%BD%8F%E5%AE%85%E5%A1%97%E8%A3%85%E3%83%AA%E3%83%95%E3%82%A9%E3%83%BC%E3%83%A0%E5%90%91%E3%81%91%E9%A1%A7%E5%AE%A2%E8%A6%81%E6%9C%9B%E5%8F%8D%E6%98%A0%E5%9E%8B%E8%87%AA%E5%8B%95%E8%A6%8B%E7%A9%8D%E7%A9%8D%E7%AE%97SaaS"
          className="mt-4 inline-block rounded-lg bg-white px-6 py-2 font-bold text-blue-700 transition hover:bg-blue-50"
        >
          詳しくはこちら →
        </Link>
      </div>

      {articles.length === 0 ? (
        <p className="text-center text-gray-500">記事はまだありません。</p>
      ) : (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {articles.map((article) => (
            <ArticleCard key={article.article_id} article={article} />
          ))}
        </div>
      )}
    </div>
  );
}
