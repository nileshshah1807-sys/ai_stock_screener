import { DEFAULT_TRIAL_DAYS } from "@/lib/billing.mjs";
import { createPublicClient } from "@/lib/supabase/public";

/**
 * The trial a new sign-up gets, in days, from the same source as the sign-up
 * trigger (trial_days() in storage/admin_plans_schema.sql). Public pages print
 * it, so a read that fails, or a database without the function yet, falls back
 * to 7, which is what the trigger gave before the setting existed.
 */
export async function getTrialDays(): Promise<number> {
  try {
    const supabase = createPublicClient();
    if (!supabase) return DEFAULT_TRIAL_DAYS;
    const { data, error } = await supabase.rpc("trial_days");
    return !error && Number.isInteger(data) && data > 0 ? data : DEFAULT_TRIAL_DAYS;
  } catch {
    return DEFAULT_TRIAL_DAYS;
  }
}
