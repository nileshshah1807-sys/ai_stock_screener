
import { NextResponse, type NextRequest } from "next/server";

import { bearerMatches } from "@/lib/bearer.mjs";
import { notifyTrialEnding } from "@/lib/customer-email-server";
import { createAdminClient } from "@/lib/supabase/admin";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

const DAY = 86_400_000;

/**
 * Daily (cron-job.org, see README): emails each customer whose free trial ends within two
 * days, once. The scheduler sends `Authorization: Bearer $CRON_SECRET`; without
 * the secret set, or a wrong one, nothing runs. A trial row that already holds
 * a plan (an old mandate set up during the trial) is left out: it is not
 * asking them to pick one.
 */
export async function GET(request: NextRequest) {
  if (!bearerMatches(request.headers.get("authorization"), process.env.CRON_SECRET)) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const admin = createAdminClient();
  if (!admin) return NextResponse.json({ error: "not_configured" }, { status: 503 });

  const now = Date.now();
  const { data, error } = await admin
    .from("subscriptions")
    .select("user_id, trial_ends_at")
    .eq("status", "trialing")
    .is("plan_id", null)
    .gt("trial_ends_at", new Date(now).toISOString())
    .lte("trial_ends_at", new Date(now + 2 * DAY).toISOString())
    .order("trial_ends_at")
    .limit(500);
  if (error) return NextResponse.json({ error: "read_failed" }, { status: 500 });

  // Skip who was already emailed, so a long window never crowds out the new ones; and members (admins, the allowlist), who are not on a trial to end.
  const ids = (data ?? []).map((r) => r.user_id);
  const [done, members] = await Promise.all([
    admin.from("customer_emails").select("user_id").eq("kind", "trial_ending").in("user_id", ids),
    admin.from("dashboard_allowlist").select("email"),
  ]);
  if (done.error || members.error) return NextResponse.json({ error: "read_failed" }, { status: 500 });
  const emailed = new Set((done.data ?? []).map((r) => r.user_id));
  const memberEmails = new Set((members.data ?? []).map((r) => String(r.email).toLowerCase()));
  // Each send is recorded before it goes: a run killed part-way must be short. The rest are still in the window tomorrow.
  const todo = (data ?? []).filter((r) => !emailed.has(r.user_id)).slice(0, 100);

  const sent: Record<string, number> = {};
  for (const row of todo) {
    const result = await notifyTrialEnding(admin, row.user_id, row.trial_ends_at, memberEmails);
    sent[result] = (sent[result] ?? 0) + 1;
  }
  return NextResponse.json({ considered: todo.length, ...sent });
}
