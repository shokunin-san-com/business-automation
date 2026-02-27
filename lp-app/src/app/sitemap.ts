import type { MetadataRoute } from "next";
import { getAllLPSlugs } from "@/lib/lp-data";
import { getAllArticleSlugs } from "@/lib/blog-data";

const BASE_URL = "https://lp-app-pi.vercel.app";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const entries: MetadataRoute.Sitemap = [
    {
      url: BASE_URL,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 1.0,
    },
    {
      url: `${BASE_URL}/blog`,
      lastModified: new Date(),
      changeFrequency: "daily",
      priority: 0.9,
    },
  ];

  // LP pages
  try {
    const lpSlugs = await getAllLPSlugs();
    for (const slug of lpSlugs) {
      entries.push({
        url: `${BASE_URL}/lp/${encodeURIComponent(slug)}`,
        lastModified: new Date(),
        changeFrequency: "weekly",
        priority: 0.8,
      });
    }
  } catch {
    /* ignore */
  }

  // Blog articles
  try {
    const articleSlugs = await getAllArticleSlugs();
    for (const slug of articleSlugs) {
      entries.push({
        url: `${BASE_URL}/blog/${encodeURIComponent(slug)}`,
        lastModified: new Date(),
        changeFrequency: "monthly",
        priority: 0.7,
      });
    }
  } catch {
    /* ignore */
  }

  return entries;
}
