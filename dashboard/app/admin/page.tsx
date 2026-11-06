import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { AdminView } from "@/components/admin/admin-view";
import { adminContext, loadUsers } from "@/lib/admin";
import { asFilter, filterRows } from "@/lib/admin.mjs";
import { getSession } from "@/lib/auth";

export const metadata: Metadata = { title: "Admin" };
export const dynamic = "force-dynamic";

export default async function AdminPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  // Checked on every request from the verified token; anyone else is sent away before any data is read.
  const ctx = await adminContext();
  if (!ctx) redirect((await getSession()) ? "/screener" : "/login");

  const params = await searchParams;
  const q = typeof params.q === "string" ? params.q.slice(0, 120) : "";
  const status = asFilter(typeof params.status === "string" ? params.status : "all");
  const all = await loadUsers(ctx.db);
  const rows = filterRows(all, { q, status });
  return <AdminView rows={rows} total={all.length} q={q} status={status} adminId={ctx.viewer.id} razorpayKeyId={process.env.RAZORPAY_KEY_ID ?? ""} />;
}
