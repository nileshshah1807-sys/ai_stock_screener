import "server-only";

import { createClient } from "@supabase/supabase-js";

/**
 * The anonymous client, with no session and no cookies: for public reads that
 * are the same for every visitor (plans, the trial length), so the pages that
 * print them can be built once and refreshed on a beat instead of rendered per
 * request. null when the project is not configured.
 */
export function createPublicClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  // A build without the env vars still builds; the page refreshes with real figures on its beat.
  if (!url || !key) return null;
  return createClient(url, key, { auth: { persistSession: false, autoRefreshToken: false } });
}
