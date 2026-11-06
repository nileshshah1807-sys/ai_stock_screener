import type { Metadata } from "next";

import { PlansAdmin } from "@/components/admin/plans/plans-admin";
import { loadPlansAdmin } from "@/lib/admin-plans";
import { requireAdmin } from "@/lib/auth";

export const metadata: Metadata = { title: "Plans" };
export const dynamic = "force-dynamic";

export default async function AdminPlansPage() {
  await requireAdmin();
  const data = await loadPlansAdmin();
  if (!data) return <p className="p-6 text-sm text-muted-foreground">Could not read plans. Is the service role configured?</p>;
  return <PlansAdmin data={data} />;
}
