import { cache } from "react";

export interface Business {
  id: string;
  business_id: string;
  slug: string;
  display_name: string;
  description: string;
  is_active: boolean;
}

const SUPABASE_CONFIGURED =
  !!process.env.NEXT_PUBLIC_SUPABASE_URL &&
  !!process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

async function getSupabase() {
  if (!SUPABASE_CONFIGURED) return null;
  const { createClient } = await import("@supabase/supabase-js");
  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    { auth: { persistSession: false } },
  );
}

export const getBusinessBySlug = cache(
  async (slug: string): Promise<Business | null> => {
    const supabase = await getSupabase();
    if (!supabase) return null;

    const { data, error } = await supabase
      .from("businesses")
      .select("*")
      .eq("slug", slug)
      .eq("is_active", true)
      .single();

    if (error || !data) return null;
    return mapRow(data);
  },
);

export const getBusinessByBusinessId = cache(
  async (businessId: string): Promise<Business | null> => {
    const supabase = await getSupabase();
    if (!supabase) return null;

    const { data, error } = await supabase
      .from("businesses")
      .select("*")
      .eq("business_id", businessId)
      .eq("is_active", true)
      .single();

    if (error || !data) return null;
    return mapRow(data);
  },
);

export async function getAllBusinesses(): Promise<Business[]> {
  const supabase = await getSupabase();
  if (!supabase) return [];

  const { data, error } = await supabase
    .from("businesses")
    .select("*")
    .eq("is_active", true)
    .order("created_at", { ascending: true });

  if (error || !data) return [];
  return data.map(mapRow);
}

export async function getAllBusinessSlugs(): Promise<string[]> {
  const supabase = await getSupabase();
  if (!supabase) return [];

  const { data, error } = await supabase
    .from("businesses")
    .select("slug")
    .eq("is_active", true);

  if (error || !data) return [];
  return data.map((r) => r.slug);
}

function mapRow(row: Record<string, unknown>): Business {
  return {
    id: String(row.id || ""),
    business_id: String(row.business_id || ""),
    slug: String(row.slug || ""),
    display_name: String(row.display_name || ""),
    description: String(row.description || ""),
    is_active: Boolean(row.is_active),
  };
}
