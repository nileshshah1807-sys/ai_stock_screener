import { OBJECTS_PATH } from "@/lib/object-gate.mjs";
import type { MarketCode } from "@/lib/markets";
import { createClient } from "@/lib/supabase/client";

/**
 * One of the R2 objects a static page shows (lib/object-gate.mjs names them), read
 * in the browser with the viewer's token; null when it is absent or the read fails,
 * so a page drops that section rather than failing.
 */
export async function readObject<T>(market: MarketCode, name: string): Promise<T | null> {
  try {
    const { data } = await createClient().auth.getSession();
    const token = data.session?.access_token;
    if (!token) return null;
    const query = new URLSearchParams({ market, name });
    const response = await fetch(`${OBJECTS_PATH}?${query}`, { headers: { authorization: `Bearer ${token}` } });
    return response.ok ? ((await response.json()) as T) : null;
  } catch {
    return null;
  }
}
