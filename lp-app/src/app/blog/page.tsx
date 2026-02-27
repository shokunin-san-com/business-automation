import { redirect } from "next/navigation";
import { getAllBusinesses } from "@/lib/business-data";

export const dynamic = "force-dynamic";

export default async function BlogRedirect() {
  const businesses = await getAllBusinesses();
  if (businesses.length > 0) {
    redirect(`/${businesses[0].slug}`);
  }
  redirect("/");
}
