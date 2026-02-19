export interface LPPainPointItem {
  icon: string;
  title: string;
  description: string;
}

export interface LPFeatureItem {
  icon: string;
  title: string;
  description: string;
}

export interface LPSocialProofItem {
  metric: string;
  label: string;
}

export interface LPFAQItem {
  question: string;
  answer: string;
}

export type LPSection =
  | { type: "pain_points"; title: string; items: LPPainPointItem[] }
  | { type: "solution"; title: string; description: string }
  | { type: "features"; title: string; items: LPFeatureItem[] }
  | { type: "social_proof"; title: string; items: LPSocialProofItem[] }
  | { type: "faq"; title: string; items: LPFAQItem[] };

export interface LPData {
  id: string;
  name: string;
  category: string;
  target_audience: string;
  headline: string;
  subheadline: string;
  sections: LPSection[];
  cta_text: string;
  cta_action: string;
  meta_description: string;
  og_title: string;
  og_description: string;
}
