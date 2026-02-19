import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { getLPData, getAllLPSlugs } from "../../../lib/lp-data";
import type { LPSection } from "../../../types/lp";
import LPHero from "../../../components/LPHero";
import LPFeatures from "../../../components/LPFeatures";
import LPSocialProof from "../../../components/LPSocialProof";
import LPFAQ from "../../../components/LPFAQ";
import LPContactForm from "../../../components/LPContactForm";
import LPFooter from "../../../components/LPFooter";

// Allow dynamic slugs not known at build time (new LPs appear without redeploy)
export const dynamicParams = true;
// Revalidate every 5 minutes so new content appears quickly
export const revalidate = 300;

type Params = Promise<{ slug: string }>;

export async function generateStaticParams() {
  const slugs = await getAllLPSlugs();
  return slugs.map((slug) => ({ slug }));
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { slug } = await params;
  const lp = await getLPData(slug);
  if (!lp) return {};
  return {
    title: lp.og_title || lp.headline,
    description: lp.meta_description,
    openGraph: {
      title: lp.og_title || lp.headline,
      description: lp.og_description || lp.meta_description,
    },
  };
}

function renderSection(section: LPSection, index: number) {
  switch (section.type) {
    case "pain_points":
      return <LPFeatures key={index} title={section.title} items={section.items} />;
    case "features":
      return <LPFeatures key={index} title={section.title} items={section.items} />;
    case "solution":
      return (
        <section key={index} className="bg-gray-50 py-16 sm:py-20">
          <div className="mx-auto max-w-3xl px-6 text-center">
            <h2 className="text-2xl font-bold text-gray-900 sm:text-3xl">
              {section.title}
            </h2>
            <p className="mt-6 text-gray-600 leading-relaxed text-lg">
              {section.description}
            </p>
          </div>
        </section>
      );
    case "social_proof":
      return <LPSocialProof key={index} title={section.title} items={section.items} />;
    case "faq":
      return <LPFAQ key={index} title={section.title} items={section.items} />;
    default:
      return null;
  }
}

export default async function LPPage({ params }: { params: Params }) {
  const { slug } = await params;
  const lp = await getLPData(slug);
  if (!lp) notFound();

  const companyName = process.env.NEXT_PUBLIC_COMPANY_NAME || "MarketProbe Project";
  const email = (lp.cta_action || "").replace("mailto:", "");

  return (
    <main>
      <LPHero
        headline={lp.headline}
        subheadline={lp.subheadline}
        ctaText={lp.cta_text}
        ctaAction="#contact"
      />
      {lp.sections.map((section, i) => renderSection(section, i))}
      <LPContactForm ctaText={lp.cta_text} email={email} businessId={lp.id} />
      <LPFooter companyName={companyName} />
    </main>
  );
}
