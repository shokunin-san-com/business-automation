import type { LPData } from "../types/lp";
import { getAllRows } from "./sheets";

const GCS_BUCKET = process.env.GCS_BUCKET_NAME || "marketprobe-automation-lps";

/**
 * Get all LP slugs from the lp_content sheet.
 */
export async function getAllLPSlugs(): Promise<string[]> {
  try {
    const rows = await getAllRows("lp_content");
    return rows.map((r) => r.business_id).filter(Boolean);
  } catch {
    return [];
  }
}

/**
 * Get LP data from GCS public bucket.
 * Falls back to lp_content sheet if GCS fetch fails.
 */
export async function getLPData(slug: string): Promise<LPData | null> {
  // Ensure slug is decoded (Next.js may pass URL-encoded Japanese)
  const decodedSlug = decodeURIComponent(slug);

  // Try GCS first
  try {
    const url = `https://storage.googleapis.com/${GCS_BUCKET}/lp_content/${encodeURIComponent(decodedSlug)}.json`;
    const res = await fetch(url, { next: { revalidate: 300 } }); // cache 5 min
    if (res.ok) {
      return (await res.json()) as LPData;
    }
  } catch {
    /* GCS unavailable, try Sheets fallback */
  }

  // Fallback: reconstruct from lp_content sheet
  try {
    const rows = await getAllRows("lp_content");
    const row = rows.find((r) => r.business_id === decodedSlug);
    if (!row) return null;

    // V2: Get market info from gate_decision_log instead of deleted business_ideas
    let ideaRow: Record<string, string> | undefined;
    try {
      const gates = await getAllRows("gate_decision_log");
      const gate = gates.find((g) => g.run_id === decodedSlug && g.status === "PASS");
      if (gate) {
        ideaRow = {
          name: gate.micro_market || "",
          category: gate.payer || "",
          target_audience: gate.payer || "",
        };
      }
    } catch { /* ignore */ }

    let sections = [];
    try {
      sections = JSON.parse(row.sections_json || "[]");
    } catch { /* ignore */ }

    // Default cta_action: use email from env or idea data
    const defaultEmail = process.env.CONTACT_EMAIL || "";
    const ctaAction = row.cta_action || (defaultEmail ? `mailto:${defaultEmail}` : "");

    return {
      id: decodedSlug,
      name: ideaRow?.name || decodedSlug,
      category: ideaRow?.category || "",
      target_audience: ideaRow?.target_audience || "",
      headline: row.headline || "",
      subheadline: row.subheadline || "",
      sections,
      cta_text: row.cta_text || "",
      cta_action: ctaAction,
      meta_description: row.meta_description || "",
      og_title: row.og_title || "",
      og_description: row.og_description || "",
    } as LPData;
  } catch {
    return null;
  }
}

/**
 * Get all LPs.
 */
export async function getAllLPs(): Promise<LPData[]> {
  const slugs = await getAllLPSlugs();
  const results = await Promise.all(slugs.map((slug) => getLPData(slug)));
  return results.filter((lp): lp is LPData => lp !== null);
}
