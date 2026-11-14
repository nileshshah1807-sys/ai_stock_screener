"use server";

import { getViewer } from "@/lib/auth";
import { MARKET_LIST, type MarketCode } from "@/lib/markets";
import { createClient } from "@/lib/supabase/server";
import {
  SAVED_VIEWS_MAX,
  cleanViewName,
  cleanViewQuery,
  legacyImportRows,
} from "@/lib/saved-views.mjs";

/**
 * Saved views in the viewer's account (storage/saved_views_schema.sql).
 *
 * Ownership is RLS's: `user_id` defaults to auth.uid() and is never sent. The
 * viewer check is getViewer() rather than requireAccess(): these run from the
 * screener's effects and clicks, where a redirect would be wrong. "Unavailable"
 * (no viewer, or the table not yet applied) sends the component back to
 * browser storage, so nothing breaks before the SQL is run.
 */

export type AccountView = { id: string; label: string; query: string };
type Failure = { ok: false; unavailable: boolean; error: string };
export type ViewsResult = { ok: true; views: AccountView[] } | Failure;

const TABLE_MISSING = new Set(["PGRST205", "42P01"]);
const MARKET_CODES = MARKET_LIST.map((market) => market.code);
const UNAVAILABLE: Failure = { ok: false, unavailable: true, error: "" };
const COLUMNS = "id, name, query, market";

type Row = { id: string; name: string; query: string; market: string };

function failure(error: { code?: string; message: string }, what: string): Failure {
  if (TABLE_MISSING.has(error.code ?? "")) return UNAVAILABLE;
  if (error.message.includes("saved_views_cap")) {
    return { ok: false, unavailable: false, error: `You can keep ${SAVED_VIEWS_MAX} views per market. Delete one first.` };
  }
  console.error(`${what} failed`, error.message);
  return { ok: false, unavailable: false, error: "Could not update your saved views." };
}

async function session(market: unknown) {
  if (!MARKET_CODES.includes(market as MarketCode)) return null;
  if (!(await getViewer())) return null;
  return createClient();
}

const toView = (row: Row): AccountView => ({ id: row.id, label: row.name, query: row.query });

/**
 * The viewer's views in one market. `legacy` is the browser's old list: it is
 * moved into the account first, in one insert; the caller clears it on success.
 */
export async function loadSavedViews(
  market: MarketCode,
  legacy: Array<{ label: string; query: string }> = [],
): Promise<ViewsResult> {
  const supabase = await session(market);
  if (!supabase) return UNAVAILABLE;

  const { data, error } = await supabase
    .from("saved_views")
    .select(COLUMNS)
    .order("created_at", { ascending: true });
  if (error) return failure(error, "loadSavedViews");
  let rows = (data ?? []) as Row[];

  if (legacy.length) {
    const names: Record<string, string[]> = {};
    for (const row of rows) (names[row.market] ??= []).push(row.name);
    const fresh = legacyImportRows(legacy, names, MARKET_CODES);
    if (fresh.length) {
      const { data: added, error: insertError } = await supabase
        .from("saved_views")
        .insert(fresh)
        .select(COLUMNS);
      if (insertError) return failure(insertError, "importSavedViews");
      rows = [...rows, ...((added ?? []) as Row[])];
    }
  }

  return { ok: true, views: rows.filter((row) => row.market === market).map(toView) };
}

/** Save under a name; the same name, in any case, is overwritten. */
export async function saveView(
  market: MarketCode,
  label: string,
  query: string,
): Promise<{ ok: true; view: AccountView } | Failure> {
  const name = cleanViewName(label);
  const clean = cleanViewQuery(query);
  if (!name || !clean) return { ok: false, unavailable: false, error: "Nothing to save." };
  const supabase = await session(market);
  if (!supabase) return UNAVAILABLE;

  const { data: existing, error: readError } = await supabase
    .from("saved_views")
    .select("id, name")
    .eq("market", market);
  if (readError) return failure(readError, "saveView");
  const same = ((existing ?? []) as Array<{ id: string; name: string }>).find(
    (row) => row.name.toLowerCase() === name.toLowerCase(),
  );

  const table = supabase.from("saved_views");
  const write = same
    ? table.update({ name, query: clean, updated_at: new Date().toISOString() }).eq("id", same.id)
    : table.insert({ market, name, query: clean });
  const { data, error } = await write.select(COLUMNS).single();
  if (error || !data) return failure(error ?? { message: "no row returned" }, "saveView");
  return { ok: true, view: toView(data as Row) };
}

export async function deleteView(market: MarketCode, id: string): Promise<ViewsResult> {
  const supabase = await session(market);
  if (!supabase) return UNAVAILABLE;
  const { error } = await supabase.from("saved_views").delete().eq("id", String(id));
  if (error) return failure(error, "deleteView");
  return { ok: true, views: [] };
}
