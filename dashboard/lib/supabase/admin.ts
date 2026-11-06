import "server-only";

import { createClient } from "@supabase/supabase-js";

/**
 * Service-role client, for the billing routes (app/api/billing/*) and the trial guard (lib/trial-guard.ts):
 * the Razorpay webhook has no signed-in user to act as, and plans'
 * razorpay_plan_id is not readable by viewers. It bypasses RLS, so never import
 * it from a page or a component, and never return what it reads without
 * choosing the fields. Null when the key is not configured.
 */
export function createAdminClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return null;
  return createClient(url, key, { auth: { persistSession: false, autoRefreshToken: false } });
}
