import { notFound } from "next/navigation";

import { AdminView } from "@/components/admin/admin-view";
import { buildRow, filterRows } from "@/lib/admin.mjs";

/** Development only: /admin from made-up users, for looking at. ?open=2 opens a row's actions; ?q= and ?status= filter. */
const DAY = 86_400_000;
const at = (days: number) => new Date(Date.now() + days * DAY).toISOString();
const user = (id: string, email: string, signedUp: number, last: number | null, name?: string) => ({
  id: `00000000-0000-4000-8000-00000000000${id}`, email, created_at: at(-signedUp), last_sign_in_at: last === null ? null : at(-last),
  user_metadata: name ? { full_name: name } : {},
});

const ALL = [
  buildRow(user("1", "priya.shah@example.com", 2, 0, "Priya Shah"), { status: "trialing", trial_ends_at: at(5), razorpay_subscription_id: null }, { granted: true, reason: "ok" }, null),
  buildRow(user("2", "arjun@example.in", 40, 1), { status: "active", plan_id: "yearly", current_period_end: at(200), razorpay_subscription_id: "sub_Pv3kT9aQ2xLm01" }, { granted: true, reason: "ok" }, null),
  buildRow(user("3", "temp.user@mailinator.com", 1, 1), { status: "expired", trial_ends_at: at(-1), trial_denied_at: at(-1) }, { granted: false, reason: "disposable_email" }, null),
  buildRow(user("4", "meera.rao@example.com", 90, 12, "Meera Rao"), { status: "cancelled", plan_id: "monthly", current_period_end: at(-20), razorpay_subscription_id: "sub_Nq8cD4wR7yZp22" }, null, null),
  buildRow(user("5", "friend@example.org", 15, 3), { status: "expired", trial_ends_at: at(-8) }, { granted: true, reason: "ok" }, { role: "viewer" }),
  buildRow(user("6", "owner@example.com", 300, 0, "Site Owner"), null, null, { role: "admin" }),
];

export default async function AdminPreview({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  if (process.env.NODE_ENV !== "development") notFound();
  const { q = "", status = "all", open } = await searchParams;
  const rows = filterRows(ALL, { q, status });
  return <AdminView rows={rows} total={ALL.length} q={q} status={status} adminId={ALL[5].id} razorpayKeyId="rzp_test_x" trialDays={14} initialOpen={open ? ALL[Number(open) - 1]?.id : null} />;
}
