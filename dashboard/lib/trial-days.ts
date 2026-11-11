import { DEFAULT_TRIAL_DAYS } from "@/lib/billing.mjs";
import { sharedRead } from "@/lib/home-cache";
import type { Reader } from "@/lib/results";
import { createClient } from "@/lib/supabase/server";

/**
 * The trial a new sign-up gets, in days, from the same source as the sign-up
 * trigger (trial_days() in storage/admin_plans_schema.sql). Public pages print
 * it, so a read that fails, or a database without the function yet, falls back
 * to 7, which is what the trigger gave before the setting existed.
 *
 * The same for everyone and changed rarely: one cross-instance entry for ten
 * minutes, so the landing page does not wait on a database round trip.
 */
export async function getTrialDays(): Promise<number> {
  try {
    return await sharedRead("trial-days", "all", 600, readTrialDays);
  } catch {
    return DEFAULT_TRIAL_DAYS;
  }
}

/** The live value, for the admin who sets it: never up to ten minutes old. */
export async function getTrialDaysLive(): Promise<number> {
  try {
    return await readTrialDays();
  } catch {
    return DEFAULT_TRIAL_DAYS;
  }
}

/** Throws on a failed read when handed the cache's client, so a failure is never kept. */
async function readTrialDays(db?: Reader): Promise<number> {
  const supabase = db ?? (await createClient());
  const { data, error } = await supabase.rpc("trial_days");
  if (error && db) throw new Error(error.message);
  return !error && Number.isInteger(data) && data > 0 ? data : DEFAULT_TRIAL_DAYS;
}
