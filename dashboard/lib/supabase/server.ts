import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

/**
 * Server-side Supabase client bound to the caller's session cookies.
 *
 * This uses the anon key, never the service role. Every read therefore runs as
 * the signed-in user and is filtered by the RLS policies in
 * storage/dashboard_schema.sql. A bug in this app's own filtering logic
 * consequently cannot leak another tenant's rows, because the database applies
 * the invite-list check independently.
 */
export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options),
            );
          } catch {
            // Server Components cannot set cookies. Token refresh is handled
            // in proxy.ts, which runs before rendering and can write them, so
            // swallowing this is safe rather than merely convenient.
          }
        },
      },
    },
  );
}
