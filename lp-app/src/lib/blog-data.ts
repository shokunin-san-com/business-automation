import type { BlogArticle } from "../types/blog";
import { getAllRows } from "./sheets";

const GCS_BUCKET = process.env.GCS_BUCKET_NAME || "marketprobe-automation-lps";

/**
 * Get all published blog article slugs.
 */
export async function getAllArticleSlugs(): Promise<string[]> {
  try {
    const rows = await getAllRows("blog_articles");
    return rows
      .filter((r) => r.status === "published")
      .map((r) => r.slug)
      .filter(Boolean);
  } catch {
    return [];
  }
}

/**
 * Get a single blog article by slug.
 * Tries GCS first, falls back to Sheets.
 */
export async function getArticle(slug: string): Promise<BlogArticle | null> {
  const decoded = decodeURIComponent(slug);

  // Try GCS first
  try {
    const url = `https://storage.googleapis.com/${GCS_BUCKET}/blog_articles/${encodeURIComponent(decoded)}.json`;
    const res = await fetch(url, { next: { revalidate: 300 } });
    if (res.ok) {
      return (await res.json()) as BlogArticle;
    }
  } catch {
    /* GCS unavailable */
  }

  // Fallback: Sheets
  try {
    const rows = await getAllRows("blog_articles");
    const row = rows.find(
      (r) => r.slug === decoded && r.status === "published",
    );
    if (!row) return null;

    let tags: string[] = [];
    try {
      tags = JSON.parse(row.tags || "[]");
    } catch {
      tags = row.tags ? row.tags.split(",").map((t: string) => t.trim()) : [];
    }

    return {
      article_id: row.article_id || "",
      business_id: row.business_id || "",
      title: row.title || "",
      slug: row.slug || "",
      body_html: row.body_html || "",
      excerpt: row.excerpt || "",
      category: row.category || "",
      tags,
      meta_description: row.meta_description || "",
      og_title: row.og_title || row.title || "",
      og_description: row.og_description || row.meta_description || "",
      status: row.status as "draft" | "published",
      published_at: row.published_at || "",
      generated_at: row.generated_at || "",
    };
  } catch {
    return null;
  }
}

/**
 * Get all published blog articles.
 */
export async function getAllArticles(
  businessId?: string,
): Promise<BlogArticle[]> {
  try {
    const rows = await getAllRows("blog_articles");
    const published = rows.filter((r) => {
      if (r.status !== "published") return false;
      if (businessId && r.business_id !== businessId) return false;
      return true;
    });

    return published.map((row) => {
      let tags: string[] = [];
      try {
        tags = JSON.parse(row.tags || "[]");
      } catch {
        tags = row.tags
          ? row.tags.split(",").map((t: string) => t.trim())
          : [];
      }

      return {
        article_id: row.article_id || "",
        business_id: row.business_id || "",
        title: row.title || "",
        slug: row.slug || "",
        body_html: "", // Don't load full body for listing
        excerpt: row.excerpt || "",
        category: row.category || "",
        tags,
        meta_description: row.meta_description || "",
        og_title: row.og_title || row.title || "",
        og_description: row.og_description || row.meta_description || "",
        status: "published",
        published_at: row.published_at || "",
        generated_at: row.generated_at || "",
      };
    });
  } catch {
    return [];
  }
}
