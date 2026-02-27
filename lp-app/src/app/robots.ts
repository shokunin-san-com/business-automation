import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: ["/dashboard", "/settings", "/login", "/api/"],
    },
    sitemap: "https://lp-app-pi.vercel.app/sitemap.xml",
  };
}
