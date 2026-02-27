import { redirect } from "next/navigation";
import { notFound } from "next/navigation";
import { getArticle } from "@/lib/blog-data";
import { getBusinessByBusinessId } from "@/lib/business-data";

export const dynamic = "force-dynamic";

export default async function BlogArticleRedirect({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const article = await getArticle(slug);
  if (!article) notFound();

  const business = await getBusinessByBusinessId(article.business_id);
  if (!business) notFound();

  redirect(`/${business.slug}/${encodeURIComponent(article.slug)}`);
}
