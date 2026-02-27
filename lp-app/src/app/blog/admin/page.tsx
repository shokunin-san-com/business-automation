export const dynamic = "force-dynamic";

export default async function AdminDashboard() {
  if (!process.env.NEXT_PUBLIC_SUPABASE_URL) {
    return (
      <div className="text-center py-12 text-gray-500">
        Supabaseが未設定です。.env.localにSUPABASE環境変数を追加してください。
      </div>
    );
  }

  const { createServiceClient } = await import("@/lib/supabase/server");
  const supabase = createServiceClient();

  const [
    { count: totalPosts },
    { count: publishedPosts },
    { count: draftPosts },
  ] = await Promise.all([
    supabase.from("posts").select("*", { count: "exact", head: true }),
    supabase
      .from("posts")
      .select("*", { count: "exact", head: true })
      .eq("status", "published"),
    supabase
      .from("posts")
      .select("*", { count: "exact", head: true })
      .eq("status", "draft"),
  ]);

  // Get category breakdown
  const { data: posts } = await supabase
    .from("posts")
    .select("category, status")
    .eq("status", "published");

  const categories: Record<string, number> = {};
  (posts || []).forEach((p: { category: string | null; status: string }) => {
    const cat = p.category || "未分類";
    categories[cat] = (categories[cat] || 0) + 1;
  });

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">ダッシュボード</h1>

      {/* Stats cards */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        <div className="rounded-lg border bg-white p-4">
          <p className="text-sm text-gray-500">全記事</p>
          <p className="text-3xl font-bold text-gray-900">{totalPosts || 0}</p>
        </div>
        <div className="rounded-lg border bg-white p-4">
          <p className="text-sm text-gray-500">公開中</p>
          <p className="text-3xl font-bold text-green-600">
            {publishedPosts || 0}
          </p>
        </div>
        <div className="rounded-lg border bg-white p-4">
          <p className="text-sm text-gray-500">下書き</p>
          <p className="text-3xl font-bold text-yellow-600">
            {draftPosts || 0}
          </p>
        </div>
      </div>

      {/* Category breakdown */}
      <div className="rounded-lg border bg-white p-6">
        <h2 className="text-lg font-bold text-gray-900 mb-4">
          カテゴリ別記事数
        </h2>
        <div className="space-y-2">
          {Object.entries(categories)
            .sort((a, b) => b[1] - a[1])
            .map(([cat, count]) => (
              <div key={cat} className="flex items-center justify-between">
                <span className="text-sm text-gray-700">{cat}</span>
                <span className="rounded-full bg-blue-100 px-3 py-0.5 text-xs font-medium text-blue-700">
                  {count}件
                </span>
              </div>
            ))}
        </div>
      </div>
    </div>
  );
}
