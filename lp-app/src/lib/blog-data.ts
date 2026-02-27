import { cache } from "react";
import type { BlogArticle, BlogArticleSummary } from "../types/blog";

const DEFAULT_MEDIA_ID = "shokunin-san";

const SUPABASE_CONFIGURED =
  !!process.env.NEXT_PUBLIC_SUPABASE_URL &&
  !!process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

async function getSupabase() {
  if (!SUPABASE_CONFIGURED) return null;
  // Use plain supabase-js client (no cookies) so it works in both
  // request scope (SSR pages) and build scope (generateStaticParams).
  const { createClient } = await import("@supabase/supabase-js");
  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    { auth: { persistSession: false } },
  );
}

/** Columns to select for article listings (no body) */
const SUMMARY_COLUMNS =
  "id, business_id, media_id, title, slug, excerpt, category, tags, meta_description, og_title, og_description, status, has_affiliate, published_at, generated_at, created_at, updated_at";

/** Columns to select for full article */
const FULL_COLUMNS = `${SUMMARY_COLUMNS}, body_html, body_json, author_id`;

/**
 * Get a single blog article by slug (cached per request).
 */
export const getArticle = cache(
  async (slug: string, mediaId?: string, businessId?: string): Promise<BlogArticle | null> => {
    const supabase = await getSupabase();
    if (!supabase) return null;

    const decoded = decodeURIComponent(slug);
    let query = supabase
      .from("posts")
      .select(FULL_COLUMNS)
      .eq("media_id", mediaId || DEFAULT_MEDIA_ID)
      .eq("slug", decoded)
      .eq("status", "published")
      .lte("published_at", new Date().toISOString());

    if (businessId) {
      query = query.eq("business_id", businessId);
    }

    const { data, error } = await query.single();

    if (error || !data) return null;

    return mapRow(data);
  },
);

/**
 * Get all published blog articles (summary only, no body).
 */
export async function getAllArticles(
  mediaId?: string,
  businessId?: string,
): Promise<BlogArticleSummary[]> {
  const supabase = await getSupabase();
  if (!supabase) return [];

  let query = supabase
    .from("posts")
    .select(SUMMARY_COLUMNS)
    .eq("media_id", mediaId || DEFAULT_MEDIA_ID)
    .eq("status", "published")
    .lte("published_at", new Date().toISOString())
    .order("published_at", { ascending: false });

  if (businessId) {
    query = query.eq("business_id", businessId);
  }

  const { data, error } = await query;

  if (error || !data) {
    console.error("[blog-data] getAllArticles error:", error);
    return [];
  }

  return data.map(mapSummaryRow);
}

/**
 * Get all published blog article slugs (for sitemap / static generation).
 */
export async function getAllArticleSlugs(
  mediaId?: string,
  businessId?: string,
): Promise<string[]> {
  const supabase = await getSupabase();
  if (!supabase) return [];

  let query = supabase
    .from("posts")
    .select("slug")
    .eq("media_id", mediaId || DEFAULT_MEDIA_ID)
    .eq("status", "published");

  if (businessId) {
    query = query.eq("business_id", businessId);
  }

  const { data, error } = await query;

  if (error || !data) return [];
  return data.map((r) => r.slug).filter(Boolean);
}

/**
 * Get articles by category (for related articles).
 */
export async function getArticlesByCategory(
  category: string,
  excludeSlug?: string,
  limit = 3,
  mediaId?: string,
  businessId?: string,
): Promise<BlogArticleSummary[]> {
  const supabase = await getSupabase();
  if (!supabase) return [];

  let query = supabase
    .from("posts")
    .select(SUMMARY_COLUMNS)
    .eq("media_id", mediaId || DEFAULT_MEDIA_ID)
    .eq("status", "published")
    .eq("category", category)
    .lte("published_at", new Date().toISOString())
    .order("published_at", { ascending: false })
    .limit(limit + 1);

  if (businessId) {
    query = query.eq("business_id", businessId);
  }

  const { data, error } = await query;

  if (error || !data) return [];

  return data
    .filter((r) => r.slug !== excludeSlug)
    .slice(0, limit)
    .map(mapSummaryRow);
}

/**
 * Get articles by tag.
 */
export async function getArticlesByTag(
  tag: string,
  mediaId?: string,
): Promise<BlogArticleSummary[]> {
  const supabase = await getSupabase();
  if (!supabase) return [];

  const { data, error } = await supabase
    .from("posts")
    .select(SUMMARY_COLUMNS)
    .eq("media_id", mediaId || DEFAULT_MEDIA_ID)
    .eq("status", "published")
    .contains("tags", [tag])
    .lte("published_at", new Date().toISOString())
    .order("published_at", { ascending: false });

  if (error || !data) return [];
  return data.map(mapSummaryRow);
}

/**
 * Get all unique categories.
 */
export async function getAllCategories(
  mediaId?: string,
  businessId?: string,
): Promise<string[]> {
  const articles = await getAllArticles(mediaId, businessId);
  const categories = new Set(articles.map((a) => a.category).filter(Boolean));
  return Array.from(categories).sort();
}

// ---- Row mappers ----

function mapRow(row: Record<string, unknown>): BlogArticle {
  return {
    id: String(row.id || ""),
    business_id: String(row.business_id || ""),
    media_id: String(row.media_id || DEFAULT_MEDIA_ID),
    title: String(row.title || ""),
    slug: String(row.slug || ""),
    body_html: String(row.body_html || ""),
    body_json: (row.body_json as Record<string, unknown>) || null,
    excerpt: String(row.excerpt || ""),
    category: String(row.category || ""),
    tags: Array.isArray(row.tags) ? row.tags : [],
    meta_description: String(row.meta_description || ""),
    og_title: String(row.og_title || row.title || ""),
    og_description: String(row.og_description || row.meta_description || ""),
    status: row.status === "published" ? "published" : "draft",
    has_affiliate: Boolean(row.has_affiliate),
    author_id: row.author_id ? String(row.author_id) : null,
    published_at: String(row.published_at || ""),
    generated_at: row.generated_at ? String(row.generated_at) : undefined,
    created_at: row.created_at ? String(row.created_at) : undefined,
    updated_at: row.updated_at ? String(row.updated_at) : undefined,
  };
}

function mapSummaryRow(row: Record<string, unknown>): BlogArticleSummary {
  return {
    id: String(row.id || ""),
    business_id: String(row.business_id || ""),
    media_id: String(row.media_id || DEFAULT_MEDIA_ID),
    title: String(row.title || ""),
    slug: String(row.slug || ""),
    excerpt: String(row.excerpt || ""),
    category: String(row.category || ""),
    tags: Array.isArray(row.tags) ? row.tags : [],
    meta_description: String(row.meta_description || ""),
    og_title: String(row.og_title || row.title || ""),
    og_description: String(row.og_description || row.meta_description || ""),
    status: row.status === "published" ? "published" : "draft",
    has_affiliate: Boolean(row.has_affiliate),
    author_id: row.author_id ? String(row.author_id) : null,
    published_at: String(row.published_at || ""),
    generated_at: row.generated_at ? String(row.generated_at) : undefined,
    created_at: row.created_at ? String(row.created_at) : undefined,
    updated_at: row.updated_at ? String(row.updated_at) : undefined,
  };
}
