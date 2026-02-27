export interface BlogArticle {
  id: string;
  business_id: string;
  media_id: string;
  title: string;
  slug: string;
  body_html: string;
  body_json?: Record<string, unknown> | null;
  excerpt: string;
  category: string;
  tags: string[];
  meta_description: string;
  og_title: string;
  og_description: string;
  status: "draft" | "published";
  has_affiliate: boolean;
  author_id?: string | null;
  published_at: string;
  generated_at?: string;
  created_at?: string;
  updated_at?: string;
}

/** Lightweight version for listing pages (no body) */
export type BlogArticleSummary = Omit<BlogArticle, "body_html" | "body_json">;
