import Link from "next/link";
import { getAllLPs } from "../lib/lp-data";

export default async function Home() {
  const lps = await getAllLPs();

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="mx-auto max-w-4xl px-6 py-16">
        <h1 className="text-3xl font-bold text-gray-900">
          MarketProbe — 事業検証ダッシュボード
        </h1>
        <p className="mt-2 text-gray-600">検証中のランディングページ一覧</p>

        {lps.length === 0 ? (
          <p className="mt-12 text-gray-400">
            まだLPが生成されていません。事業案をactiveにしてLP生成を実行してください。
          </p>
        ) : (
          <div className="mt-10 grid gap-6 sm:grid-cols-2">
            {lps.map((lp) => (
              <Link
                key={lp.id}
                href={`/lp/${lp.id}`}
                className="block rounded-xl border border-gray-200 bg-white p-6 shadow-sm hover:shadow-md transition"
              >
                <span className="inline-block rounded-full bg-blue-100 px-3 py-1 text-xs font-medium text-blue-700">
                  {lp.category}
                </span>
                <h2 className="mt-3 text-lg font-semibold text-gray-900">
                  {lp.name}
                </h2>
                <p className="mt-2 text-sm text-gray-600 line-clamp-2">
                  {lp.headline}
                </p>
              </Link>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
