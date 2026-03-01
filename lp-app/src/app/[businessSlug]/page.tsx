import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getAllArticles, getAllCategories } from "@/lib/blog-data";
import { getBusinessBySlug, getAllBusinessSlugs } from "@/lib/business-data";
import type { BlogArticleSummary } from "@/types/blog";

export const dynamic = "force-dynamic";

export async function generateStaticParams() {
  const slugs = await getAllBusinessSlugs();
  return slugs.map((businessSlug) => ({ businessSlug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ businessSlug: string }>;
}): Promise<Metadata> {
  const { businessSlug } = await params;
  const business = await getBusinessBySlug(businessSlug);
  if (!business) return { title: "Not Found" };

  return {
    title: `${business.display_name} ブログ | 職人さんドットコム`,
    description: `${business.description || business.display_name}に関する最新情報をお届けします。`,
  };
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  return d.toLocaleDateString("ja-JP", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function PostCard({ article, basePath }: { article: BlogArticleSummary; basePath: string }) {
  return (
    <article className="group relative flex overflow-hidden rounded-xl bg-white border border-gray-100 transition-all duration-200 hover:border-blue-200 hover:shadow-sm">
      <div className="relative w-32 flex-shrink-0 overflow-hidden sm:w-40 bg-gradient-to-br from-blue-50 to-slate-50">
        {article.cover_image ? (
          <img
            src={article.cover_image}
            alt=""
            className="absolute inset-0 h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
            loading="lazy"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center">
            <svg className="h-7 w-7 text-blue-200" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1} aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5a2.25 2.25 0 002.25-2.25V5.25a2.25 2.25 0 00-2.25-2.25H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" />
            </svg>
          </div>
        )}
      </div>
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
          <Link href={`${basePath}/${encodeURIComponent(article.slug)}`}>
            <span className="absolute inset-0" />
            {article.title}
          </Link>
        </h3>
        {article.tags && article.tags.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {article.tags.slice(0, 3).map((tag) => (
              <span key={tag} className="inline-block rounded px-2 py-0.5 text-[10px] font-medium bg-gray-50 text-gray-500">
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

function FeaturedCard({ article, basePath }: { article: BlogArticleSummary; basePath: string }) {
  return (
    <article className="group relative overflow-hidden rounded-xl bg-white border border-gray-100 transition-all duration-200 hover:border-blue-200 hover:shadow-sm">
      <div className="relative aspect-[2.2/1] overflow-hidden bg-gradient-to-br from-blue-50 to-slate-100">
        {article.cover_image ? (
          <img
            src={article.cover_image}
            alt=""
            className="absolute inset-0 h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center">
            <svg className="h-12 w-12 text-blue-200" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={0.8} aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5a2.25 2.25 0 002.25-2.25V5.25a2.25 2.25 0 00-2.25-2.25H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" />
            </svg>
          </div>
        )}
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
          <Link href={`${basePath}/${encodeURIComponent(article.slug)}`}>
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
  basePath,
  lpUrl,
  businessName,
}: {
  recentPosts: BlogArticleSummary[];
  allCategories: string[];
  activeCategory: string;
  basePath: string;
  lpUrl: string;
  businessName: string;
}) {
  return (
    <div className="sticky top-24 space-y-6">
      <div className="rounded-xl bg-gradient-to-br from-blue-600 to-blue-800 p-5 text-white">
        <h3 className="text-sm font-bold">{businessName}に興味がありますか？</h3>
        <p className="mt-2 text-xs text-blue-100 leading-relaxed">
          AIを活用した業務自動化で、効率化とコスト削減を実現します。
        </p>
        <Link
          href={lpUrl}
          className="mt-3 inline-block rounded-lg bg-white px-4 py-2 text-xs font-bold text-blue-700 transition hover:bg-blue-50"
        >
          詳しくはこちら →
        </Link>
      </div>

      {allCategories.length > 0 && (
        <div className="rounded-xl bg-white p-5 border border-gray-100">
          <h3 className="mb-3 text-[13px] font-semibold text-gray-800">カテゴリー</h3>
          <ul className="space-y-1.5">
            <li>
              <Link
                href={basePath}
                className={`block rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors ${
                  !activeCategory ? "bg-blue-50 text-blue-700" : "text-gray-500 hover:bg-gray-50 hover:text-gray-700"
                }`}
              >
                すべての記事
              </Link>
            </li>
            {allCategories.map((cat) => (
              <li key={cat}>
                <Link
                  href={`${basePath}?category=${encodeURIComponent(cat)}`}
                  className={`block rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors ${
                    activeCategory === cat ? "bg-blue-50 text-blue-700" : "text-gray-500 hover:bg-gray-50 hover:text-gray-700"
                  }`}
                >
                  {cat}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      {recentPosts.length > 0 && (
        <div className="rounded-xl bg-white p-5 border border-gray-100">
          <h3 className="mb-3 text-[13px] font-semibold text-gray-800">最新の記事</h3>
          <ul className="space-y-3">
            {recentPosts.map((post) => (
              <li key={post.id}>
                <Link href={`${basePath}/${encodeURIComponent(post.slug)}`} className="group flex gap-3">
                  <div className="relative h-12 w-12 flex-shrink-0 overflow-hidden rounded-lg bg-gradient-to-br from-blue-50 to-slate-50">
                    {post.cover_image ? (
                      <img src={post.cover_image} alt="" className="absolute inset-0 h-full w-full object-cover" loading="lazy" />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center">
                        <svg className="h-3.5 w-3.5 text-blue-200" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5a2.25 2.25 0 002.25-2.25V5.25a2.25 2.25 0 00-2.25-2.25H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" />
                        </svg>
                      </div>
                    )}
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

export default async function BusinessBlogPage({
  params,
  searchParams,
}: {
  params: Promise<{ businessSlug: string }>;
  searchParams: Promise<{ category?: string }>;
}) {
  const { businessSlug } = await params;
  const business = await getBusinessBySlug(businessSlug);
  if (!business) notFound();

  const { category } = await searchParams;
  const basePath = `/${businessSlug}`;
  const lpUrl = `/lp/${encodeURIComponent(business.business_id)}`;

  const [articles, categories] = await Promise.all([
    getAllArticles(undefined, business.business_id),
    getAllCategories(undefined, business.business_id),
  ]);

  const filtered = category
    ? articles.filter((a) => a.category === category)
    : articles;

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      {/* Hero Section */}
      <section className="relative mb-10 overflow-hidden rounded-2xl bg-slate-900 px-8 py-20 sm:px-12 sm:py-24">
        <div
          className="pointer-events-none absolute -right-4 top-1/2 -translate-y-1/2 select-none text-[100px] font-bold leading-none tracking-tight text-white/[0.04] sm:text-[150px]"
          aria-hidden="true"
        >
          職人
          <br />
          さん
        </div>
        <div className="relative max-w-xl">
          <p className="text-[10px] tracking-[0.3em] text-white/40 uppercase font-mono">
            職人さんドットコム
          </p>
          <h1 className="mt-6 text-[26px] font-bold leading-[1.6] text-white sm:text-[32px] sm:leading-[1.55]">
            {business.display_name}
          </h1>
          <div className="mt-6 h-px w-12 bg-white/25" />
          <p className="mt-6 text-[13px] leading-[1.8] text-white/50">
            {business.description}
          </p>
        </div>
      </section>

      {/* Tag Pills (mobile) */}
      {categories.length > 0 && (
        <div className="mb-10 flex gap-2 overflow-x-auto scrollbar-none pb-1 lg:hidden">
          <Link
            href={basePath}
            className={`flex flex-shrink-0 items-center gap-1.5 rounded-md px-4 py-2 text-[12px] font-medium transition-colors ${
              !category ? "bg-blue-600 text-white" : "bg-white text-gray-400 border border-gray-100"
            }`}
          >
            すべて
          </Link>
          {categories.map((cat) => (
            <Link
              key={cat}
              href={`${basePath}?category=${encodeURIComponent(cat)}`}
              className={`flex flex-shrink-0 items-center gap-1.5 rounded-md px-4 py-2 text-[12px] font-medium transition-colors ${
                category === cat ? "bg-blue-600 text-white" : "bg-white text-gray-400 border border-gray-100"
              }`}
            >
              {cat}
            </Link>
          ))}
        </div>
      )}

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
          <div className="lg:col-span-8">
            {!category && filtered.length > 0 && (
              <section className="mb-12">
                <SectionTitle>ピックアップ</SectionTitle>
                <FeaturedCard article={filtered[0]} basePath={basePath} />
              </section>
            )}
            {(() => {
              const listPosts = category ? filtered : filtered.slice(1);
              return listPosts.length > 0 ? (
                <section className="mb-12">
                  <SectionTitle>{category ? `「${category}」の記事` : "新着記事"}</SectionTitle>
                  <div className="space-y-4">
                    {listPosts.map((article) => (
                      <PostCard key={article.id} article={article} basePath={basePath} />
                    ))}
                  </div>
                </section>
              ) : null;
            })()}
          </div>
          <div className="lg:col-span-4">
            <Sidebar
              recentPosts={articles.slice(0, 5)}
              allCategories={categories}
              activeCategory={category || ""}
              basePath={basePath}
              lpUrl={lpUrl}
              businessName={business.display_name}
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
              <Link href={basePath} className="mt-4 text-sm font-medium text-blue-600">
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
