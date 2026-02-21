import { NextResponse } from "next/server";
import { getAllRows } from "@/lib/sheets";

interface BusinessIdea {
  id: string;
  name: string;
  category: string;
  description: string;
  target_audience: string;
  status: string;
  created_at: string;
  has_lp: boolean;
}

export async function GET() {
  try {
    const [ideas, lpRows] = await Promise.all([
      getAllRows("business_ideas").catch(() => []),
      getAllRows("lp_content").catch(() => []),
    ]);

    const lpBusinessIds = new Set(
      lpRows.map((r) => r.business_id || r.id || "").filter(Boolean)
    );

    const mapped: BusinessIdea[] = ideas.map((row) => ({
      id: row.id || "",
      name: row.name || "",
      category: row.category || "",
      description: row.description || "",
      target_audience: row.target_audience || "",
      status: row.status || "draft",
      created_at: row.created_at || "",
      has_lp: lpBusinessIds.has(row.id || ""),
    }));

    const active = mapped.filter((i) => i.status === "active");
    const draft = mapped.filter((i) => i.status === "draft");
    const archived = mapped.filter((i) => i.status === "archived");

    return NextResponse.json({
      active,
      draft,
      archived,
      totalCount: mapped.length,
      activeCount: active.length,
    });
  } catch {
    return NextResponse.json({
      active: [],
      draft: [],
      archived: [],
      totalCount: 0,
      activeCount: 0,
    });
  }
}
