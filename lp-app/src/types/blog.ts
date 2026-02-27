export interface BlogArticle {
  article_id: string;
  business_id: string;
  title: string;
  slug: string;
  body_html: string;
  excerpt: string;
  category: string;
  tags: string[];
  meta_description: string;
  og_title: string;
  og_description: string;
  status: "draft" | "published";
  published_at: string;
  generated_at?: string;
}
