"use server";

import { revalidatePath } from "next/cache";

import { requireAccess } from "@/lib/auth";
import { createClient } from "@/lib/supabase/server";
import { WATCHLIST_MAX_LISTS, WATCHLIST_MAX_SYMBOLS } from "@/lib/types";

/**
 * Watchlist mutations.
 *
 * Every one of these calls requireAccess() first. RLS already refuses a write
 * from anyone who is not the owner and on the invite list, so this is not the
 * security boundary -- it is what turns "the database silently wrote nothing"
 * into a redirect and an error the caller can show. A route handler or action
 * that forgot it would appear to succeed while doing nothing.
 *
 * `owner_id` is never sent. It defaults to auth.uid() in the schema and the RLS
 * with-check refuses any other value, so ownership is not something this file
 * can get wrong.
 */

export type ActionResult = { ok: true } | { ok: false; error: string };

/** Both watchlist surfaces read the same rows, so both must be revalidated. */
function revalidateWatchlistViews(symbol?: string): void {
  revalidatePath("/watchlists");
  if (symbol) revalidatePath(`/stocks/${symbol}`);
}

function cleanName(raw: FormDataEntryValue | null): string {
  return String(raw ?? "").trim().replace(/\s+/g, " ").slice(0, 60);
}

function cleanSymbol(raw: FormDataEntryValue | null): string {
  return String(raw ?? "").trim().toUpperCase().slice(0, 32);
}

export async function createWatchlist(formData: FormData): Promise<ActionResult> {
  await requireAccess();
  const name = cleanName(formData.get("name"));
  if (!name) return { ok: false, error: "Give the list a name." };

  const supabase = await createClient();

  // Counted rather than left to a constraint: there is no database-level way to
  // express "at most twenty rows per owner" without a trigger, and the limit
  // exists for the selector's layout rather than for storage.
  const { count } = await supabase
    .from("watchlists")
    .select("id", { count: "exact", head: true });
  if ((count ?? 0) >= WATCHLIST_MAX_LISTS) {
    return {
      ok: false,
      error: `You already have ${WATCHLIST_MAX_LISTS} lists. Delete one first.`,
    };
  }

  const { error } = await supabase.from("watchlists").insert({ name });

  if (error) {
    // 23505 is unique_violation, from watchlists_owner_name_idx. Reported as
    // the human problem rather than the Postgres one.
    if (error.code === "23505") {
      return { ok: false, error: `You already have a list called “${name}”.` };
    }
    console.error("createWatchlist failed", error.message);
    return { ok: false, error: "Could not create the list." };
  }

  revalidateWatchlistViews();
  return { ok: true };
}

export async function renameWatchlist(formData: FormData): Promise<ActionResult> {
  await requireAccess();
  const id = String(formData.get("id") ?? "");
  const name = cleanName(formData.get("name"));
  if (!id) return { ok: false, error: "Missing list." };
  if (!name) return { ok: false, error: "Give the list a name." };

  const supabase = await createClient();
  const { error } = await supabase
    .from("watchlists")
    .update({ name, updated_at: new Date().toISOString() })
    .eq("id", id);

  if (error) {
    if (error.code === "23505") {
      return { ok: false, error: `You already have a list called “${name}”.` };
    }
    console.error("renameWatchlist failed", error.message);
    return { ok: false, error: "Could not rename the list." };
  }

  revalidateWatchlistViews();
  return { ok: true };
}

export async function deleteWatchlist(formData: FormData): Promise<ActionResult> {
  await requireAccess();
  const id = String(formData.get("id") ?? "");
  if (!id) return { ok: false, error: "Missing list." };

  const supabase = await createClient();
  // Members go with it via `on delete cascade`, so this is one statement rather
  // than a delete of items followed by a delete of the list, which could leave
  // orphans if the second failed.
  const { error } = await supabase.from("watchlists").delete().eq("id", id);

  if (error) {
    console.error("deleteWatchlist failed", error.message);
    return { ok: false, error: "Could not delete the list." };
  }

  revalidateWatchlistViews();
  return { ok: true };
}

export async function addToWatchlist(formData: FormData): Promise<ActionResult> {
  await requireAccess();
  const watchlistId = String(formData.get("watchlistId") ?? "");
  const symbol = cleanSymbol(formData.get("symbol"));
  if (!watchlistId || !symbol) return { ok: false, error: "Missing list or symbol." };

  const supabase = await createClient();

  const { count } = await supabase
    .from("watchlist_items")
    .select("symbol", { count: "exact", head: true })
    .eq("watchlist_id", watchlistId);
  if ((count ?? 0) >= WATCHLIST_MAX_SYMBOLS) {
    return {
      ok: false,
      error: `That list is full at ${WATCHLIST_MAX_SYMBOLS} symbols.`,
    };
  }

  // upsert, not insert: adding a symbol that is already on the list is what a
  // double click looks like, and it should be a no-op rather than an error.
  const { error } = await supabase
    .from("watchlist_items")
    .upsert({ watchlist_id: watchlistId, symbol }, { onConflict: "watchlist_id,symbol" });

  if (error) {
    console.error("addToWatchlist failed", error.message);
    return { ok: false, error: "Could not add to the list." };
  }

  await touch(watchlistId);
  revalidateWatchlistViews(symbol);
  return { ok: true };
}

export async function removeFromWatchlist(
  formData: FormData,
): Promise<ActionResult> {
  await requireAccess();
  const watchlistId = String(formData.get("watchlistId") ?? "");
  const symbol = cleanSymbol(formData.get("symbol"));
  if (!watchlistId || !symbol) return { ok: false, error: "Missing list or symbol." };

  const supabase = await createClient();
  const { error } = await supabase
    .from("watchlist_items")
    .delete()
    .eq("watchlist_id", watchlistId)
    .eq("symbol", symbol);

  if (error) {
    console.error("removeFromWatchlist failed", error.message);
    return { ok: false, error: "Could not remove from the list." };
  }

  await touch(watchlistId);
  revalidateWatchlistViews(symbol);
  return { ok: true };
}

/**
 * Bump `updated_at` after a membership change.
 *
 * Deliberately fire-and-forget: the selector orders by this, so a failure means
 * lists appear in a slightly stale order. Failing the whole add because the
 * timestamp did not move would be the wrong trade.
 */
async function touch(watchlistId: string): Promise<void> {
  const supabase = await createClient();
  const { error } = await supabase
    .from("watchlists")
    .update({ updated_at: new Date().toISOString() })
    .eq("id", watchlistId);
  if (error) console.error("watchlist touch failed", error.message);
}
