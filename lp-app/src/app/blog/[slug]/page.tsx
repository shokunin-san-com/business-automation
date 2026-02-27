import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getArticle, getAllArticles, getAllArticleSlugs } from "@/lib/blog-data";

export const dynamicParams = true;
export const revalidate = 300;

export async function generateStaticParams() {
  const slugs = await getAllArticleSlugs();
  return slugs.map((slug) => ({ slug: encodeURIComponent(slug) }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const article = await getArticle(slug);
  if (!article) return { title: "記事が見つかりません" };

  return {
    title: `${article.og_title || article.title} | MarketProbe ブログ`,
    description: article.meta_description || article.excerpt,
    openGraph: {
      title: article.og_title || article.title,
      description: article.og_description || article.meta_description,
      type: "article",
      publishedTime: article.published_at,
    },
  };
}

function ArticleCTA() {
  return (
    <div className="mt-10 rounded-xl border-2 border-blue-200 bg-blue-50 p-6 text-center">
      <h3 className="text-xl font-bold text-gray-900">
        住宅塗装の見積もりを自動化しませんか？
      </h3>
      <p className="mt-2 text-gray-600">
        AIが顧客の要望を反映した最適な見積もりを自動生成。初月無料でお試しいただけます。
      </p>
      <Link
        href="/lp/%E4%BD%8F%E5%AE%85%E5%A1%97%E8%A3%85%E3%83%AA%E3%83%95%E3%82%A9%E3%83%BC%E3%83%A0%E5%90%91%E3%81%91%E9%A1%A7%E5%AE%A2%E8%A6%81%E6%9C%9B%E5%8F%8D%E6%98%A0%E5%9E%8B%E8%87%AA%E5%8B%95%E8%A6%8B%E7%A9%8D%E7%A9%8D%E7%AE%97SaaS"
        className="mt-4 inline-block rounded-lg bg-blue-600 px-8 py-3 font-bold text-white transition hover:bg-blue-700"
      >
        無料で試してみる →
      </Link>
    </div>
  );
}

function JsonLd({ article }: { article: { title: string; meta_description: string; published_at: string; slug: string } }) {
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    headline: article.title,
    description: article.meta_description,
    datePublished: article.published_at,
    author: {
      "@type": "Organization",
      name: "MarketProbe",
    },
    publisher: {
      "@type": "Organization",
      name: "MarketProbe",
    },
    mainEntityOfPage: {
      "@type": "WebPage",
      "@id": `https://lp-app-pi.vercel.app/blog/${encodeURIComponent(article.slug)}`,
    },
  };

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
    />
  );
}

export default async function BlogArticlePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const article = await getArticle(slug);

  if (!article) {
    notFound();
  }

  // Get related articles (same category, max 3)
  const allArticles = await getAllArticles(article.business_id);
  const related = allArticles
    .filter(
      (a) =>
        a.article_id !== article.article_id &&
        a.category === article.category,
    )
    .slice(0, 3);

  const publishedDate = article.published_at
    ? new Date(article.published_at).toLocaleDateString("ja-JP")
    : "";

  return (
    <>
      <JsonLd article={article} />
      <article className="mx-auto max-w-3xl px-4 py-12">
        {/* Breadcrumb */}
        <nav className="mb-6 text-sm text-gray-500">
          <Link href="/blog" className="hover:text-blue-600">
            ブログ
          </Link>
          <span className="mx-2">/</span>
          <span className="text-gray-700">{article.title}</span>
        </nav>

        {/* Header */}
        <header className="mb-8">
          <div className="mb-3 flex items-center gap-3">
            {article.category && (
              <span className="rounded-full bg-blue-100 px-3 py-1 text-xs font-medium text-blue-700">
                {article.category}
              </span>
            )}
            {publishedDate && (
              <time className="text-sm text-gray-400">{publishedDate}</time>
            )}
          </div>
          <h1 className="text-3xl font-bold leading-tight text-gray-900">
            {article.title}
          </h1>
        </header>

        {/* Body */}
        <div
          className="prose prose-lg max-w-none prose-headings:text-gray-900 prose-h2:mt-8 prose-h2:mb-4 prose-h2:text-2xl prose-h3:mt-6 prose-h3:mb-3 prose-p:text-gray-700 prose-p:leading-relaxed prose-a:text-blue-600 prose-a:no-underline hover:prose-a:underline prose-li:text-gray-700 prose-strong:text-gray-900"
          dangerouslySetInnerHTML={{ __html: article.body_html }}
        />

        {/* CTA */}
        <ArticleCTA />

        {/* Tags */}
        {article.tags.length > 0 && (
          <div className="mt-8 flex flex-wrap gap-2">
            {article.tags.map((tag) => (
              <span
                key={tag}
                className="rounded-full bg-gray-100 px-3 py-1 text-xs text-gray-600"
              >
                #{tag}
              </span>
            ))}
          </div>
        )}

        {/* Related articles */}
        {related.length > 0 && (
          <section className="mt-12 border-t pt-8">
            <h2 className="mb-6 text-xl font-bold text-gray-900">
              関連記事
            </h2>
            <div className="grid gap-4 sm:grid-cols-3">
              {related.map((r) => (
                <Link
                  key={r.article_id}
                  href={`/blog/${encodeURIComponent(r.slug)}`}
                  className="block rounded-lg border p-4 transition hover:shadow-md"
                >
                  <h3 className="text-sm font-bold text-gray-900 line-clamp-2">
                    {r.title}
                  </h3>
                  <p className="mt-1 text-xs text-gray-500 line-clamp-2">
                    {r.excerpt}
                  </p>
                </Link>
              ))}
            </div>
          </section>
        )}
      </article>
    </>
  );
}
