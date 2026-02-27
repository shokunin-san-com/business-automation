import { NextResponse } from "next/server";
import { getAllRows } from "@/lib/sheets";

/**
 * GET /api/blog — Debug: check blog_articles sheet access
 */
export async function GET() {
  try {
    const rows = await getAllRows("blog_articles");
    const summary = rows.slice(0, 3).map((r) => ({
      article_id: r.article_id,
      title: r.title,
      slug: r.slug,
      status: r.status,
      category: r.category,
    }));
    return NextResponse.json({
      total: rows.length,
      published: rows.filter((r) => r.status === "published").length,
      sample: summary,
    });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
