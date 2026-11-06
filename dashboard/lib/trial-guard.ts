import "server-only";

import { createHmac } from "node:crypto";
import { cookies, headers } from "next/headers";

import type { SupabaseClient } from "@supabase/supabase-js";

import { TRIAL_WINDOW_DAYS, ipKey, isDisposableEmail, normalizeEmail, trialVerdict } from "@/lib/trial-guard.mjs";
import { DEVICE_COOKIE } from "@/lib/device-cookie";
import { createAdminClient } from "@/lib/supabase/admin";



/**
 * Decide whether a newly signed-in person keeps the free trial the sign-up
 * trigger gave them; if not, end it. Runs once per user (their trial_signals row
 * is the memory). Returns true when the trial was ended, so the caller can
 * refresh the session token. Fails open: no salt, no service key or a read error
 * leaves the trial as it is.
 */
export async function guardTrial(input: {
  userId: string;
  email: string;
  ip: string | null;
  deviceId: string | null;
}): Promise<boolean> {
  const salt = process.env.TRIAL_GUARD_SALT;
  const admin = createAdminClient();
  if (!salt || !admin) {
    console.warn("Trial guard off: TRIAL_GUARD_SALT or the service key is not set");
    return false;
  }
  const hash = (value: string | null) => (value ? createHmac("sha256", salt).update(value).digest("hex") : null);

  const { data: seen, error: seenError } = await admin
    .from("trial_signals").select("user_id").eq("user_id", input.userId).maybeSingle();
  if (seenError || seen) return false;

  const ipHash = hash(ipKey(input.ip));
  const deviceHash = hash(input.deviceId);
  const emailHash = hash(normalizeEmail(input.email))!;
  const since = new Date(Date.now() - TRIAL_WINDOW_DAYS * 86_400_000).toISOString();
  const matches = [`email_hash.eq.${emailHash}`];
  if (ipHash) matches.push(`ip_hash.eq.${ipHash}`);
  if (deviceHash) matches.push(`device_hash.eq.${deviceHash}`);
  const { data: priors, error } = await admin
    .from("trial_signals").select("ip_hash, device_hash, email_hash")
    .eq("granted", true).gte("created_at", since).or(matches.join(","));
  if (error) {
    console.error("Trial guard could not read earlier trials", error.message);
    return false;
  }

  const verdict = trialVerdict(
    { ipHash, deviceHash, emailHash, disposable: isDisposableEmail(input.email) },
    priors ?? [],
  );
  const { error: writeError } = await admin.from("trial_signals").insert({
    user_id: input.userId, ip_hash: ipHash, device_hash: deviceHash, email_hash: emailHash,
    granted: verdict.grant, reason: verdict.reason,
  });
  if (writeError || verdict.grant) return false;

  // Only a trial with no plan set up: never touch a paying row.
  const { error: revokeError } = await admin
    .from("subscriptions")
    .update({ status: "expired", trial_ends_at: new Date().toISOString(), trial_denied_at: new Date().toISOString() })
    .eq("user_id", input.userId).eq("status", "trialing").is("plan_id", null);
  if (revokeError) console.error("Trial guard could not end the trial", revokeError.message);
  return !revokeError;
}

/**
 * After a sign-in: run the guard for the signed-in user and, when it ended the
 * trial, refresh the session so the token carries plan=none straight away.
 */
export async function enforceTrialGuard(supabase: SupabaseClient) {
  try {
    const { data } = await supabase.auth.getUser();
    const user = data.user;
    if (!user?.email) return;
    const [h, c] = [await headers(), await cookies()];
    const ended = await guardTrial({
      userId: user.id,
      email: user.email,
      ip: h.get("x-real-ip") ?? h.get("x-forwarded-for"),
      deviceId: c.get(DEVICE_COOKIE)?.value ?? null,
    });
    if (ended) await supabase.auth.refreshSession();
  } catch (error) {
    console.error("Trial guard failed", error);
  }
}
