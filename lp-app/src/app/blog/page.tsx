import type { Metadata } from "next";
import Link from "next/link";
import { getAllArticles, getAllCategories } from "@/lib/blog-data";
import type { BlogArticleSummary } from "@/types/blog";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "ブログ | 職人さん.xyz",
  description:
    "塗装・リフォーム業界のDX、見積もり自動化、業務効率化に関する最新情報をお届けします。",
};

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  return d.toLocaleDateString("ja-JP", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function PostCard({ article }: { article: BlogArticleSummary }) {
  return (
    <article className="group relative flex overflow-hidden rounded-xl bg-white border border-gray-100 transition-all duration-200 hover:border-blue-200 hover:shadow-sm">
      {/* Thumbnail placeholder */}
      <div className="relative w-32 flex-shrink-0 overflow-hidden sm:w-40 bg-gradient-to-br from-blue-50 to-slate-50">
        <div className="flex h-full w-full items-center justify-center">
          <svg className="h-7 w-7 text-blue-200" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5a2.25 2.25 0 002.25-2.25V5.25a2.25 2.25 0 00-2.25-2.25H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" />
          </svg>
        </div>
      </div>

      {/* Content */}
      <div className="flex flex-1 flex-col justify-center px-5 py-4">
        <div className="mb-1.5 flex items-center gap-2">
          {article.category && (
            <span className="inline-block rounded bg-blue-50 px-2 py-0.5 text-[10px] font-medium text-blue-600">
              {article.category}
            </span>
          )}
          <time className="text-[11px] font-medium text-gray-400" dateTime={article.published_at}>
            {formatDate(article.published_at)}
          </time>
        </div>
        <h3 className="text-[14px] font-medium leading-snug text-gray-800 transition-colors group-hover:text-blue-600">
          <Link href={`/blog/${encodeURIComponent(article.slug)}`}>
            <span className="absolute inset-0" />
            {article.title}
          </Link>
        </h3>
        {article.tags && article.tags.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {article.tags.slice(0, 3).map((tag) => (
              <span
                key={tag}
                className="inline-block rounded px-2 py-0.5 text-[10px] font-medium bg-gray-50 text-gray-500"
              >
                {tag}
              </span>
            ))}
          </div>
        )}
        {article.excerpt && (
          <p className="mt-1.5 line-clamp-2 text-[12px] leading-relaxed text-gray-400">
            {article.excerpt}
          </p>
        )}
      </div>
    </article>
  );
}

function FeaturedCard({ article }: { article: BlogArticleSummary }) {
  return (
    <article className="group relative overflow-hidden rounded-xl bg-white border border-gray-100 transition-all duration-200 hover:border-blue-200 hover:shadow-sm">
      {/* Cover placeholder */}
      <div className="relative aspect-[2.2/1] overflow-hidden bg-gradient-to-br from-blue-50 to-slate-100">
        <div className="flex h-full w-full items-center justify-center">
          <svg className="h-12 w-12 text-blue-200" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={0.8} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5a2.25 2.25 0 002.25-2.25V5.25a2.25 2.25 0 00-2.25-2.25H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" />
          </svg>
        </div>
      </div>
      <div className="p-6 sm:p-8">
        <div className="mb-3 flex items-center gap-3">
          <span className="rounded px-2 py-0.5 text-[10px] font-bold tracking-wider bg-blue-600 text-white uppercase">
            NEW
          </span>
          <time className="text-xs text-gray-400" dateTime={article.published_at}>
            {formatDate(article.published_at)}
          </time>
        </div>
        <h2 className="text-xl font-bold text-gray-800 transition-colors sm:text-2xl group-hover:text-blue-600">
          <Link href={`/blog/${encodeURIComponent(article.slug)}`}>
            <span className="absolute inset-0" />
            {article.title}
          </Link>
        </h2>
        <p className="mt-3 line-clamp-2 max-w-lg text-sm leading-relaxed text-gray-400">
          {article.excerpt}
        </p>
      </div>
    </article>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-5">
      <h2 className="text-[15px] font-bold text-gray-800">{children}</h2>
      <div className="mt-2 h-px w-10 bg-blue-600" />
    </div>
  );
}

function Sidebar({
  recentPosts,
  allCategories,
  activeCategory,
}: {
  recentPosts: BlogArticleSummary[];
  allCategories: string[];
  activeCategory: string;
}) {
  return (
    <div className="sticky top-24 space-y-6">
      {/* CTA Card */}
      <div className="rounded-xl bg-gradient-to-br from-blue-600 to-blue-800 p-5 text-white">
        <h3 className="text-sm font-bold">見積もり自動化に興味がありますか？</h3>
        <p className="mt-2 text-xs text-blue-100 leading-relaxed">
          AIが顧客の要望を反映した最適な見積もりを自動生成。
        </p>
        <Link
          href="/lp/%E4%BD%8F%E5%AE%85%E5%A1%97%E8%A3%85%E3%83%AA%E3%83%95%E3%82%A9%E3%83%BC%E3%83%A0%E5%90%91%E3%81%91%E9%A1%A7%E5%AE%A2%E8%A6%81%E6%9C%9B%E5%8F%8D%E6%98%A0%E5%9E%8B%E8%87%AA%E5%8B%95%E8%A6%8B%E7%A9%8D%E7%A9%8D%E7%AE%97SaaS"
          className="mt-3 inline-block rounded-lg bg-white px-4 py-2 text-xs font-bold text-blue-700 transition hover:bg-blue-50"
        >
          詳しくはこちら →
        </Link>
      </div>

      {/* Categories */}
      {allCategories.length > 0 && (
        <div className="rounded-xl bg-white p-5 border border-gray-100">
          <h3 className="mb-3 text-[13px] font-semibold text-gray-800">カテゴリー</h3>
          <ul className="space-y-1.5">
            <li>
              <Link
                href="/blog"
                className={`block rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors ${
                  !activeCategory
                    ? "bg-blue-50 text-blue-700"
                    : "text-gray-500 hover:bg-gray-50 hover:text-gray-700"
                }`}
              >
                すべての記事
              </Link>
            </li>
            {allCategories.map((cat) => (
              <li key={cat}>
                <Link
                  href={`/blog?category=${encodeURIComponent(cat)}`}
                  className={`block rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors ${
                    activeCategory === cat
                      ? "bg-blue-50 text-blue-700"
                      : "text-gray-500 hover:bg-gray-50 hover:text-gray-700"
                  }`}
                >
                  {cat}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Recent posts */}
      {recentPosts.length > 0 && (
        <div className="rounded-xl bg-white p-5 border border-gray-100">
          <h3 className="mb-3 text-[13px] font-semibold text-gray-800">最新の記事</h3>
          <ul className="space-y-3">
            {recentPosts.map((post) => (
              <li key={post.id}>
                <Link href={`/blog/${encodeURIComponent(post.slug)}`} className="group flex gap-3">
                  <div className="relative h-12 w-12 flex-shrink-0 overflow-hidden rounded-lg bg-gradient-to-br from-blue-50 to-slate-50">
                    <div className="flex h-full w-full items-center justify-center">
                      <svg className="h-3.5 w-3.5 text-blue-200" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5a2.25 2.25 0 002.25-2.25V5.25a2.25 2.25 0 00-2.25-2.25H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" />
                      </svg>
                    </div>
                  </div>
                  <div className="flex flex-1 flex-col justify-center">
                    <span className="line-clamp-2 text-[12px] font-medium leading-snug text-gray-600 transition-colors group-hover:text-blue-600">
                      {post.title}
                    </span>
                    <time className="mt-1 text-[10px] text-gray-400" dateTime={post.published_at}>
                      {formatDate(post.published_at)}
                    </time>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default async function BlogPage({
  searchParams,
}: {
  searchParams: Promise<{ category?: string }>;
}) {
  const { category } = await searchParams;
  const [articles, categories] = await Promise.all([
    getAllArticles(),
    getAllCategories(),
  ]);

  const filtered = category
    ? articles.filter((a) => a.category === category)
    : articles;

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      {/* Hero Section */}
      <section className="relative mb-10 overflow-hidden rounded-2xl bg-slate-900 px-8 py-20 sm:px-12 sm:py-24">
        {/* Background watermark */}
        <div
          className="pointer-events-none absolute -right-4 top-1/2 -translate-y-1/2 select-none text-[100px] font-bold leading-none tracking-tight text-white/[0.04] sm:text-[150px]"
          aria-hidden="true"
        >
          職人
          <br />
          さん
        </div>

        {/* Content */}
        <div className="relative max-w-xl">
          <p className="text-[10px] tracking-[0.3em] text-white/40 uppercase font-mono">
            Automate · Estimate · Grow
          </p>
          <h1 className="mt-6 text-[26px] font-bold leading-[1.6] text-white sm:text-[32px] sm:leading-[1.55]">
            塗装業界のDXで、
            <br />
            ビジネスを加速する。
          </h1>
          <div className="mt-6 h-px w-12 bg-white/25" />
          <p className="mt-6 text-[13px] leading-[1.8] text-white/50">
            見積もり自動化・業務効率化・成約率アップ。
            <br />
            塗装リフォーム業界の最新ノウハウをお届けします。
          </p>
        </div>
      </section>

      {/* Tag Pills (horizontal scroll) */}
      {categories.length > 0 && (
        <div className="mb-10 flex gap-2 overflow-x-auto scrollbar-none pb-1 lg:hidden">
          <Link
            href="/blog"
            className={`flex flex-shrink-0 items-center gap-1.5 rounded-md px-4 py-2 text-[12px] font-medium transition-colors ${
              !category
                ? "bg-blue-600 text-white"
                : "bg-white text-gray-400 border border-gray-100"
            }`}
          >
            すべて
          </Link>
          {categories.map((cat) => (
            <Link
              key={cat}
              href={`/blog?category=${encodeURIComponent(cat)}`}
              className={`flex flex-shrink-0 items-center gap-1.5 rounded-md px-4 py-2 text-[12px] font-medium transition-colors ${
                category === cat
                  ? "bg-blue-600 text-white"
                  : "bg-white text-gray-400 border border-gray-100"
              }`}
            >
              {cat}
            </Link>
          ))}
        </div>
      )}

      {/* Active category heading */}
      {category && (
        <div className="mb-8 flex items-center gap-3">
          <span className="inline-flex items-center gap-1.5 rounded-md bg-blue-50 px-3 py-1.5 text-sm font-medium text-blue-700">
            {category}
          </span>
          <span className="text-sm text-gray-400">{filtered.length} 件の記事</span>
        </div>
      )}

      {filtered.length > 0 ? (
        <div className="grid gap-10 lg:grid-cols-12">
          {/* Main Column */}
          <div className="lg:col-span-8">
            {/* Featured Article (only when not filtering) */}
            {!category && filtered.length > 0 && (
              <section className="mb-12">
                <SectionTitle>ピックアップ</SectionTitle>
                <FeaturedCard article={filtered[0]} />
              </section>
            )}

            {/* Article List */}
            {(() => {
              const listPosts = category ? filtered : filtered.slice(1);
              return listPosts.length > 0 ? (
                <section className="mb-12">
                  <SectionTitle>{category ? `「${category}」の記事` : "新着記事"}</SectionTitle>
                  <div className="space-y-4">
                    {listPosts.map((article) => (
                      <PostCard key={article.id} article={article} />
                    ))}
                  </div>
                </section>
              ) : null;
            })()}
          </div>

          {/* Sidebar */}
          <div className="lg:col-span-4">
            <Sidebar
              recentPosts={articles.slice(0, 5)}
              allCategories={categories}
              activeCategory={category || ""}
            />
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center rounded-xl bg-white py-24 border border-gray-100">
          <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-xl bg-blue-50">
            <svg className="h-6 w-6 text-blue-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
            </svg>
          </div>
          {category ? (
            <>
              <p className="text-base font-medium text-gray-700">「{category}」の記事はまだありません</p>
              <Link href="/blog" className="mt-4 text-sm font-medium text-blue-600">
                ← すべての記事を見る
              </Link>
            </>
          ) : (
            <>
              <p className="text-base font-medium text-gray-700">まだ記事がありません</p>
              <p className="mt-1.5 text-sm text-gray-400">最初の記事を公開するとここに表示されます</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
