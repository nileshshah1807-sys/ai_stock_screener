import "server-only";

import { createClient } from "@supabase/supabase-js";

import { withMarketTables } from "@/lib/db/market-repository";

/**
 * Service-role client, for the billing routes (app/api/billing/*), the trial guard (lib/trial-guard.ts)
 * and the Home page's cached market reads (lib/home-cache.ts: the same rows for every viewer, explicit
 * non-rating columns, filtered on market). The Razorpay webhook has no signed-in user to act as, and
 * plans' razorpay_plan_id is not readable by viewers. It bypasses RLS, so never import
 * it from a page or a component, and never return what it reads without
 * choosing the fields. Null when the key is not configured.
 */
export function createAdminClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return null;
  const client = createClient(url, key, { auth: { persistSession: false, autoRefreshToken: false } });
  // A moved market table is read with the service role's reach. A *_visible source is gated (no ratings);
  // base screener_snapshot is not, so a shared-cache caller must name its columns (lib/home-market.ts does).
  return withMarketTables(client, async () => ({ admin: false }));
}
