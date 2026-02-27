import Link from "next/link";
import { getAllBusinesses } from "@/lib/business-data";
import { getAllArticles } from "@/lib/blog-data";

export default async function Home() {
  const businesses = await getAllBusinesses();

  const businessCards = await Promise.all(
    businesses.map(async (biz) => {
      const articles = await getAllArticles(undefined, biz.business_id);
      return { ...biz, articleCount: articles.length };
    }),
  );

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="mx-auto max-w-5xl px-6 py-16">
        {/* Header */}
        <div className="mb-12 text-center">
          <p className="text-[10px] tracking-[0.3em] text-gray-400 uppercase font-mono mb-4">
            職人さん.xyz
          </p>
          <h1 className="text-3xl font-bold text-gray-900 sm:text-4xl">
            業界DXの最前線
          </h1>
          <p className="mt-3 text-gray-500">
            AI・自動化で変わる業界の最新ノウハウをお届けします。
          </p>
        </div>

        {businessCards.length === 0 ? (
          <p className="text-center text-gray-400 py-20">
            コンテンツを準備中です。
          </p>
        ) : (
          <div className="grid gap-6 sm:grid-cols-2">
            {businessCards.map((biz) => (
              <Link
                key={biz.id}
                href={`/${biz.slug}`}
                className="group block overflow-hidden rounded-xl border border-gray-200 bg-white transition-all hover:border-blue-200 hover:shadow-md"
              >
                {/* Card header */}
                <div className="bg-gradient-to-r from-slate-900 to-slate-800 px-6 py-8">
                  <h2 className="text-lg font-bold text-white group-hover:text-blue-200 transition-colors">
                    {biz.display_name}
                  </h2>
                  <p className="mt-2 text-sm text-white/50 line-clamp-2">
                    {biz.description}
                  </p>
                </div>
                {/* Card body */}
                <div className="flex items-center justify-between px-6 py-4">
                  <div className="flex items-center gap-4">
                    <span className="flex items-center gap-1.5 text-sm text-gray-500">
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                      </svg>
                      {biz.articleCount} 記事
                    </span>
                  </div>
                  <span className="text-sm font-medium text-blue-600 group-hover:text-blue-700">
                    記事を読む →
                  </span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
