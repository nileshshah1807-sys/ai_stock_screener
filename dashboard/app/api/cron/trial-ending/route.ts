import { timingSafeEqual } from "node:crypto";

import { NextResponse, type NextRequest } from "next/server";

import { notifyTrialEnding } from "@/lib/customer-email-server";
import { createAdminClient } from "@/lib/supabase/admin";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

const DAY = 86_400_000;

/**
 * Daily (vercel.json): emails each customer whose free trial ends within two
 * days, once. Vercel Cron sends `Authorization: Bearer $CRON_SECRET`; without
 * the secret set, or a wrong one, nothing runs. A trial row that already holds
 * a plan (an old mandate set up during the trial) is left out: it is not
 * asking them to pick one.
 */
export async function GET(request: NextRequest) {
  const secret = process.env.CRON_SECRET;
  const given = Buffer.from(request.headers.get("authorization") ?? "");
  const want = Buffer.from(`Bearer ${secret}`);
  if (!secret || given.length !== want.length || !timingSafeEqual(given, want)) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
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
    .limit(100) // each send is recorded before it goes: a run killed part-way must be short. The rest are still in the window tomorrow.;
  if (error) return NextResponse.json({ error: "read_failed" }, { status: 500 });

  const sent: Record<string, number> = {};
  for (const row of data ?? []) {
    const result = await notifyTrialEnding(admin, row.user_id, row.trial_ends_at);
    sent[result] = (sent[result] ?? 0) + 1;
  }
  return NextResponse.json({ considered: data?.length ?? 0, ...sent });
}
