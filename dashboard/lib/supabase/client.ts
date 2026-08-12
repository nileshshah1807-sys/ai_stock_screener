import { createBrowserClient } from "@supabase/ssr";

/**
 * Browser Supabase client. Only ever receives the anon key, which is public by
 * design; RLS is what actually protects the data.
 */
export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
