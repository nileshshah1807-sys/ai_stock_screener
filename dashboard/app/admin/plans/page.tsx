import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { PlansAdmin } from "@/components/admin/plans/plans-admin";
import { adminContext } from "@/lib/admin";
import { loadPlansAdmin } from "@/lib/admin-plans-server";
import { getSession } from "@/lib/auth";

export const metadata: Metadata = { title: "Plans" };
export const dynamic = "force-dynamic";

export default async function AdminPlansPage() {
  // Checked on every request from the verified token; anyone else is sent away before any data is read.
  if (!(await adminContext())) redirect((await getSession()) ? "/screener" : "/login");
  const data = await loadPlansAdmin();
  if (!data) return <p role="alert" className="panel p-4 text-sm text-destructive">Could not read plans. Check the Supabase service key and try again.</p>;
  return <PlansAdmin data={data} />;
}
