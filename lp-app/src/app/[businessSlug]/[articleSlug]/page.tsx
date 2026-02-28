import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getArticle,
  getAllArticleSlugs,
  getAllArticles,
  getArticlesByCategory,
} from "@/lib/blog-data";
import {
  getBusinessBySlug,
  getAllBusinesses,
} from "@/lib/business-data";

export const dynamicParams = true;
export const revalidate = 300;

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  return d.toLocaleDateString("ja-JP", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export async function generateStaticParams() {
  const businesses = await getAllBusinesses();
  const params: { businessSlug: string; articleSlug: string }[] = [];
  for (const biz of businesses) {
    const slugs = await getAllArticleSlugs(undefined, biz.business_id);
    for (const slug of slugs) {
      params.push({
        businessSlug: biz.slug,
        articleSlug: encodeURIComponent(slug),
      });
    }
  }
  return params;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ businessSlug: string; articleSlug: string }>;
}): Promise<Metadata> {
  const { businessSlug, articleSlug } = await params;
  const business = await getBusinessBySlug(businessSlug);
  if (!business) return { title: "記事が見つかりません" };

  const article = await getArticle(articleSlug, undefined, business.business_id);
  if (!article) return { title: "記事が見つかりません" };

  return {
    title: `${article.og_title || article.title} | ${business.display_name}`,
    description: article.meta_description || article.excerpt,
    openGraph: {
      title: article.og_title || article.title,
      description: article.og_description || article.meta_description,
      type: "article",
      publishedTime: article.published_at,
    },
  };
}

function ArticleCTA({ lpUrl }: { lpUrl: string }) {
  return (
    <div className="mt-12 rounded-xl border border-blue-100 bg-gradient-to-br from-blue-50 to-white p-8 text-center">
      <h3 className="text-xl font-bold text-gray-800">
        住宅塗装の見積もりを自動化しませんか？
      </h3>
      <p className="mt-3 text-sm text-gray-500 leading-relaxed max-w-md mx-auto">
        AIが顧客の要望を反映した最適な見積もりを自動生成。初月無料でお試しいただけます。
      </p>
      <Link
        href={lpUrl}
        className="mt-5 inline-block rounded-lg bg-blue-600 px-8 py-3 text-sm font-bold text-white transition hover:bg-blue-700"
      >
        無料で試してみる →
      </Link>
    </div>
  );
}

function JsonLd({
  article,
  businessSlug,
}: {
  article: {
    title: string;
    meta_description: string;
    published_at: string;
    slug: string;
  };
  businessSlug: string;
}) {
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    headline: article.title,
    description: article.meta_description,
    datePublished: article.published_at,
    author: {
      "@type": "Organization",
      name: "職人さん.xyz",
    },
    publisher: {
      "@type": "Organization",
      name: "職人さん.xyz",
    },
    mainEntityOfPage: {
      "@type": "WebPage",
      "@id": `https://shokunin-san.xyz/${businessSlug}/${encodeURIComponent(article.slug)}`,
    },
  };

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
    />
  );
}

export default async function ArticlePage({
  params,
}: {
  params: Promise<{ businessSlug: string; articleSlug: string }>;
}) {
  const { businessSlug, articleSlug } = await params;
  const business = await getBusinessBySlug(businessSlug);
  if (!business) notFound();

  const article = await getArticle(articleSlug, undefined, business.business_id);
  if (!article) notFound();

  const basePath = `/${businessSlug}`;
  const lpUrl = `/lp/${encodeURIComponent(business.business_id)}`;

  const [related, allArticles] = await Promise.all([
    getArticlesByCategory(article.category, article.slug, 4, undefined, business.business_id),
    getAllArticles(undefined, business.business_id),
  ]);

  const recentPosts = allArticles
    .filter((a) => a.slug !== article.slug)
    .slice(0, 5);

  const publishedDate = formatDate(article.published_at);

  return (
    <>
      <JsonLd article={article} businessSlug={businessSlug} />
      <div className="mx-auto max-w-6xl px-6 py-10">
        <div className="grid gap-10 lg:grid-cols-12">
          {/* Main Article */}
          <article className="max-w-none lg:col-span-8">
            {/* Article Header */}
            <div className="mb-10 border-b border-gray-100 pb-10">
              {/* Breadcrumb */}
              <nav aria-label="パンくずリスト" className="mb-8">
                <ol className="flex flex-wrap items-center gap-1.5 text-[13px] text-gray-400">
                  <li>
                    <Link href="/" className="font-medium no-underline transition-colors hover:text-blue-600">
                      ホーム
                    </Link>
                  </li>
                  <li aria-hidden="true">
                    <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                    </svg>
                  </li>
                  <li>
                    <Link href={basePath} className="font-medium no-underline transition-colors hover:text-blue-600">
                      {business.display_name}
                    </Link>
                  </li>
                  {article.category && (
                    <>
                      <li aria-hidden="true">
                        <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                        </svg>
                      </li>
                      <li>
                        <Link
                          href={`${basePath}?category=${encodeURIComponent(article.category)}`}
                          className="font-medium no-underline transition-colors hover:text-blue-600"
                        >
                          {article.category}
                        </Link>
                      </li>
                    </>
                  )}
                  <li aria-hidden="true">
                    <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                    </svg>
                  </li>
                  <li className="line-clamp-1 text-gray-700">
                    {article.title}
                  </li>
                </ol>
              </nav>

              <h1 className="mb-4 text-2xl font-bold tracking-tight text-gray-800 sm:text-3xl leading-tight">
                {article.title}
              </h1>

              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-gray-400">
                <div className="flex items-center gap-1.5">
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
                  </svg>
                  <time dateTime={article.published_at}>{publishedDate}</time>
                </div>
              </div>

              {article.tags.length > 0 && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {article.tags.map((tag) => (
                    <span
                      key={tag}
                      className="inline-flex items-center gap-1 rounded-md px-3 py-1 text-[12px] font-medium bg-gray-50 text-gray-500"
                    >
                      <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9.568 3H5.25A2.25 2.25 0 003 5.25v4.318c0 .597.237 1.17.659 1.591l9.581 9.581c.699.699 1.78.872 2.607.33a18.095 18.095 0 005.223-5.223c.542-.827.369-1.908-.33-2.607L11.16 3.66A2.25 2.25 0 009.568 3z" />
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 6h.008v.008H6V6z" />
                      </svg>
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Cover Image */}
            {article.cover_image && (
              <div className="relative mb-10 aspect-[2/1] overflow-hidden rounded-xl">
                <Image
                  src={article.cover_image}
                  alt={article.title}
                  fill
                  sizes="(max-width: 768px) 100vw, 66vw"
                  className="object-cover"
                  priority
                />
              </div>
            )}

            {/* Article Body */}
            <div
              className="
                prose prose-gray max-w-none lg:prose-lg
                prose-headings:text-gray-800
                prose-h2:mt-14 prose-h2:mb-6 prose-h2:text-xl prose-h2:border-l-[3px] prose-h2:border-blue-500 prose-h2:pl-4
                prose-h3:mt-10 prose-h3:mb-4 prose-h3:text-lg
                prose-p:mb-6 prose-p:leading-[1.9] prose-p:text-gray-600 prose-p:tracking-wide
                prose-a:text-blue-600 prose-a:decoration-blue-200 prose-a:underline-offset-2 hover:prose-a:text-blue-800 hover:prose-a:decoration-blue-400
                prose-strong:text-gray-800
                prose-blockquote:border-l-[3px] prose-blockquote:border-blue-200 prose-blockquote:pl-4 prose-blockquote:not-italic prose-blockquote:text-gray-500
                prose-ul:text-gray-600 prose-ol:text-gray-600
                prose-li:leading-[1.8]
                prose-img:max-w-full prose-img:h-auto prose-img:rounded-xl prose-img:my-10
              "
              dangerouslySetInnerHTML={{ __html: article.body_html }}
            />

            {/* CTA */}
            <ArticleCTA lpUrl={lpUrl} />

            {/* Related Posts */}
            {related.length > 0 && (
              <section className="mt-16 border-t border-gray-100 pt-10">
                <h2 className="mb-6 text-lg font-bold text-gray-800">あわせて読みたい</h2>
                <div className="grid gap-4 sm:grid-cols-2">
                  {related.map((r) => (
                    <Link
                      key={r.id}
                      href={`${basePath}/${encodeURIComponent(r.slug)}`}
                      className="group flex gap-3 rounded-xl border border-gray-100 bg-white p-4 transition-colors hover:border-blue-200"
                    >
                      <div className="relative h-16 w-16 flex-shrink-0 overflow-hidden rounded-lg bg-gradient-to-br from-blue-50 to-slate-50">
                        {r.cover_image ? (
                          <Image src={r.cover_image} alt="" fill sizes="64px" className="object-cover" />
                        ) : (
                          <div className="flex h-full w-full items-center justify-center">
                            <svg className="h-4 w-4 text-blue-200" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5a2.25 2.25 0 002.25-2.25V5.25a2.25 2.25 0 00-2.25-2.25H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" />
                            </svg>
                          </div>
                        )}
                      </div>
                      <div className="flex flex-1 flex-col justify-center">
                        <span className="line-clamp-2 text-[13px] font-medium leading-snug text-gray-600 transition-colors group-hover:text-blue-600">
                          {r.title}
                        </span>
                        {r.excerpt && (
                          <p className="mt-1 line-clamp-1 text-[11px] text-gray-400">{r.excerpt}</p>
                        )}
                      </div>
                    </Link>
                  ))}
                </div>
              </section>
            )}
          </article>

          {/* Sidebar */}
          <aside className="hidden lg:col-span-4 lg:block">
            <div className="sticky top-24 space-y-6">
              <div className="rounded-xl bg-gradient-to-br from-blue-600 to-blue-800 p-5 text-white">
                <h3 className="text-sm font-bold">見積もり自動化ツール</h3>
                <p className="mt-2 text-xs text-blue-100 leading-relaxed">
                  AIが顧客の要望を反映した最適な見積もりを自動生成。
                </p>
                <Link
                  href={lpUrl}
                  className="mt-3 inline-block rounded-lg bg-white px-4 py-2 text-xs font-bold text-blue-700 transition hover:bg-blue-50"
                >
                  詳しくはこちら →
                </Link>
              </div>

              {recentPosts.length > 0 && (
                <div className="rounded-xl bg-white p-5 border border-gray-100">
                  <h3 className="mb-3 text-[13px] font-semibold text-gray-800">他の記事</h3>
                  <ul className="space-y-3">
                    {recentPosts.map((rp) => (
                      <li key={rp.id}>
                        <Link href={`${basePath}/${encodeURIComponent(rp.slug)}`} className="group flex gap-3">
                          <div className="relative h-12 w-12 flex-shrink-0 overflow-hidden rounded-lg bg-gradient-to-br from-blue-50 to-slate-50">
                            {rp.cover_image ? (
                              <Image src={rp.cover_image} alt="" fill sizes="48px" className="object-cover" />
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
                              {rp.title}
                            </span>
                            <time className="mt-1 text-[10px] text-gray-400" dateTime={rp.published_at}>
                              {formatDate(rp.published_at)}
                            </time>
                          </div>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </aside>
        </div>
      </div>
    </>
  );
}
