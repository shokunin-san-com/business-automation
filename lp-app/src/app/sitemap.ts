import type { MetadataRoute } from "next";
import { getAllLPSlugs } from "@/lib/lp-data";
import { getAllArticleSlugs } from "@/lib/blog-data";
import { getAllBusinesses } from "@/lib/business-data";

const BASE_URL = "https://shokunin-san.xyz";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const entries: MetadataRoute.Sitemap = [
    {
      url: BASE_URL,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 1.0,
    },
  ];

  // Business-scoped blog pages
  try {
    const businesses = await getAllBusinesses();
    for (const biz of businesses) {
      // Business blog listing
      entries.push({
        url: `${BASE_URL}/${biz.slug}`,
        lastModified: new Date(),
        changeFrequency: "daily",
        priority: 0.9,
      });

      // Articles for this business
      const slugs = await getAllArticleSlugs(undefined, biz.business_id);
      for (const slug of slugs) {
        entries.push({
          url: `${BASE_URL}/${biz.slug}/${encodeURIComponent(slug)}`,
          lastModified: new Date(),
          changeFrequency: "monthly",
          priority: 0.7,
        });
      }
    }
  } catch {
    /* ignore */
  }

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

  return entries;
}
