import "server-only";

import { getViewer, type Viewer } from "@/lib/auth";
import { buildRow, canAdminister, logEntry } from "@/lib/admin.mjs";
import { createAdminClient } from "@/lib/supabase/admin";

export type AdminRow = ReturnType<typeof buildRow>;

/**
 * The only door to /admin's data and actions. It re-reads the verified token
 * (getViewer -> getClaims) on every call and returns the service-role client
 * only to an admin; the page and each action call it first, and nothing a
 * client sent decides who is allowed.
 */
export async function adminContext(): Promise<{ viewer: Viewer; db: NonNullable<ReturnType<typeof createAdminClient>> } | null> {
  const viewer = await getViewer();
  if (!canAdminister(viewer)) return null;
  const db = createAdminClient();
  return db && viewer ? { viewer, db } : null;
}

type Db = NonNullable<ReturnType<typeof createAdminClient>>;

const PAGE = 1000;
const MAX_PAGES = 20;

/** Every user with their subscription, trial-guard result and allowlist row, newest first. */
export async function loadUsers(db: Db): Promise<AdminRow[]> {
  const users = [];
  for (let page = 1; page <= MAX_PAGES; page++) {
    const { data, error } = await db.auth.admin.listUsers({ page, perPage: PAGE });
    if (error) throw error;
    users.push(...data.users);
    if (data.users.length < PAGE) break;
  }
  const [subs, signals, members] = await Promise.all([
    db.from("subscriptions").select("user_id, plan_id, status, trial_ends_at, current_period_end, razorpay_subscription_id, trial_denied_at"),
    db.from("trial_signals").select("user_id, granted, reason"),
    db.from("dashboard_allowlist").select("email, role"),
  ]);
  if (subs.error) throw subs.error;
  const bySub = new Map((subs.data ?? []).map((row) => [row.user_id, row]));
  // trial_signals exists only once trial_guard_schema.sql is applied.
  const bySignal = new Map((signals.error ? [] : (signals.data ?? [])).map((row) => [row.user_id, row]));
  const byEmail = new Map((members.data ?? []).map((row) => [String(row.email).toLowerCase(), row]));
  return users
    .map((u) => buildRow(u, bySub.get(u.id) ?? null, bySignal.get(u.id) ?? null, byEmail.get((u.email ?? "").toLowerCase()) ?? null))
    .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
}

/** Cancel at once. True on success; the caller stops if it is false. */
export async function cancelRazorpay(subscriptionId: string): Promise<boolean> {
  const keyId = process.env.RAZORPAY_KEY_ID;
  const keySecret = process.env.RAZORPAY_KEY_SECRET;
  if (!keyId || !keySecret) return false;
  const response = await fetch(`https://api.razorpay.com/v1/subscriptions/${subscriptionId}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Basic ${Buffer.from(`${keyId}:${keySecret}`).toString("base64")}` },
    body: JSON.stringify({ cancel_at_cycle_end: 0 }),
  }).catch(() => null);
  return Boolean(response?.ok);
}

/**
 * Writes one admin_actions line (who, what, target, when) and returns "" or a
 * sentence to show the admin when the log could not be written. Every admin
 * page logs through this, with the context adminContext() returned.
 */
export async function logAdminAction(
  ctx: NonNullable<Awaited<ReturnType<typeof adminContext>>>,
  action: string,
  target: { id?: string | null; email?: string | null } = {},
  detail: Record<string, unknown> = {},
): Promise<string> {
  const { error } = await ctx.db.from("admin_actions").insert(logEntry(ctx.viewer, action, target, detail));
  return error ? " It was not logged: apply storage/admin_actions_schema.sql." : "";
}
