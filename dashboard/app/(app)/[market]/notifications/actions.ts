"use server";

import { requireAccess } from "@/lib/auth";
import { marketFromSlug } from "@/lib/markets";
import { createClient } from "@/lib/supabase/server";

/**
 * Record that the viewer has looked at this market's notifications.
 *
 * One timestamp per viewer and market: everything recorded after it is unread.
 * `user_id` is never sent -- it defaults to auth.uid() and RLS refuses any
 * other value -- so this cannot mark someone else's feed as read.
 *
 * Nothing is revalidated. The bell's state lives in the market layout, which
 * the client already updates itself; forcing the layout to re-render for a
 * badge would re-read the run manifest on every open.
 */
export async function markNotificationsSeen(slug: string): Promise<void> {
  await requireAccess();
  const market = marketFromSlug(slug);
  if (!market) return;
  const supabase = await createClient();
  const { error } = await supabase
    .from("notification_reads")
    .upsert(
      { market: market.code, seen_at: new Date().toISOString() },
      { onConflict: "user_id,market" },
    );
  if (error) console.error("markNotificationsSeen failed", error.message);
}
