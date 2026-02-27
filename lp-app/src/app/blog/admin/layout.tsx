"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
const NAV_ITEMS = [
  { href: "/blog/admin", label: "ダッシュボード" },
  { href: "/blog/admin/posts", label: "記事管理" },
];

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const [user, setUser] = useState<{ email: string } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    if (!url || !key) {
      setLoading(false);
      return;
    }
    import("@/lib/supabase/client")
      .then(({ createClient }) => {
        const supabase = createClient();
        return supabase.auth.getUser();
      })
      .then(({ data }) => {
        setUser(data.user ? { email: data.user.email || "" } : null);
        setLoading(false);
      })
      .catch(() => {
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-gray-400">Loading...</div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900 mb-4">
            管理者ログイン
          </h1>
          <p className="text-gray-500 mb-6">
            Supabase Authでログインしてください
          </p>
          <Link
            href="/blog/admin/login"
            className="rounded-lg bg-blue-600 px-6 py-3 text-white font-bold hover:bg-blue-700"
          >
            ログイン
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Sidebar */}
      <aside className="w-56 border-r bg-white flex flex-col">
        <div className="p-4 border-b">
          <Link href="/blog/admin" className="text-lg font-bold text-gray-900">
            Blog Admin
          </Link>
          <p className="text-xs text-gray-400 truncate mt-1">{user.email}</p>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`block rounded-lg px-3 py-2 text-sm font-medium transition ${
                pathname === item.href
                  ? "bg-blue-50 text-blue-700"
                  : "text-gray-600 hover:bg-gray-100"
              }`}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="p-3 border-t">
          <Link
            href="/blog"
            className="block rounded-lg px-3 py-2 text-sm text-gray-500 hover:bg-gray-100"
          >
            ← ブログに戻る
          </Link>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto p-6">{children}</main>
    </div>
  );
}
