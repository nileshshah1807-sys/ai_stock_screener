import "server-only";

import { getCloudflareContext } from "@opennextjs/cloudflare";

import { RESULT_FEED } from "@/lib/db/d1-views.mjs";
import { compile, decode, evaluate, TableQuery, UnsupportedQuery } from "@/lib/db/table-query.mjs";
import { readLiveObject } from "@/lib/live-objects";
import { isRatingField } from "@/lib/ratings.mjs";

/**
 * Where the market data tables are read from: Supabase, Cloudflare D1, or an
 * R2 live object (docs/d1_migration_plan.md). Login, billing, watchlists and
 * notification_reads stay on Supabase whatever the setting.
 *
 * `TABLE_BACKEND` (a Worker variable) picks, per table: unset or "supabase"
 * reads everything from Supabase, as before; "d1" reads every table listed
 * below from Cloudflare; a comma list ("market_events,concall_feed") moves
 * only those, so tables flip one by one as their backfill is verified, and
 * flip back without a deploy.
 *
 * `withMarketTables` is the one seam: it replaces a Supabase client's `from`,
 * so every reader keeps its code and its return shape, and a moved table is
 * answered by `TableQuery` instead.
 */

type Database = "core" | "evidence" | "history";
type Source =
  | { kind: "d1"; database: Database; table: string; from: string; gated?: boolean }
  | { kind: "object"; table: string; object: string };

const D1_BINDINGS: Record<Database, string> = { core: "D1_CORE", evidence: "D1_EVIDENCE", history: "D1_HISTORY" };

const d1 = (database: Database, table: string, extra: Partial<Source> = {}): Source =>
  ({ kind: "d1", database, table, from: `"${table}"`, ...extra }) as Source;


/** The name a reader asks Supabase for -> where it lives off Supabase. */
const SOURCES: Record<string, Source> = {
  concall_feed: d1("core", "concall_feed"),
  valuation_basis: d1("core", "valuation_basis"),
  quarterly_filings: d1("core", "quarterly_filings"),
  quarterly_result_feed: d1("core", "quarterly_filings", { from: RESULT_FEED }),
  financial_statements: d1("core", "financial_statements"),
  upcoming_events: d1("core", "upcoming_events"),
  market_events: d1("core", "market_events"),
  new_listings: d1("core", "new_listings"),
  universe_index: d1("core", "universe_index"),
  market_breadth: d1("core", "market_breadth"),
  // The *_visible views null ratings for a non-admin; D1 has no views, so `gated` does it here.
  screener_runs_visible: d1("core", "screener_runs", { gated: true }),
  bulk_block_deals: d1("evidence", "bulk_block_deals"),
  shareholding_patterns: d1("evidence", "shareholding_patterns"),
  company_documents: d1("evidence", "company_documents"),
  screener_history_visible: d1("history", "screener_history", { gated: true }),
  index_members: { kind: "object", table: "index_members", object: "index-members" },
  market_calendar: { kind: "object", table: "market_calendar", object: "calendar" },
};

/** Boolean columns, which D1 holds as 0/1 (from the Supabase schema files). */
const BOOLEANS = new Set(["has_data", "is_consolidated", "baseline", "has_consolidated", "has_standalone", "git_dirty", "factor_model_applied"]);

function setting(): string {
  try {
    const value = (getCloudflareContext().env as Record<string, unknown>).TABLE_BACKEND;
    if (typeof value === "string") return value.trim();
  } catch {
    // Off Cloudflare (next dev, tests): the process environment.
  }
  return (process.env.TABLE_BACKEND ?? "").trim();
}

/** Whether `table` (the base table, or "live_quotes" for the live objects) is read off Supabase. */
export function readsFromCloudflare(table: string): boolean {
  const value = setting();
  if (!value || value === "supabase") return false;
  return value === "d1" || value.split(",").some((name) => name.trim() === table);
}

function routed(name: string): Source | null {
  const source = SOURCES[name];
  return source && readsFromCloudflare(source.table) ? source : null;
}

/** The D1 binding's slice used here (the worker types are not a dependency). */
type D1Statement = object;
type D1Database = {
  prepare(sql: string): { bind(...args: unknown[]): D1Statement };
  batch(statements: D1Statement[]): Promise<{ results: Record<string, unknown>[] }[]>;
};

function binding(database: Database): D1Database {
  const db = (getCloudflareContext().env as Record<string, unknown>)[D1_BINDINGS[database]] as D1Database | undefined;
  if (!db) throw new Error(`no D1 binding ${D1_BINDINGS[database]}`);
  return db;
}

/*
 * Statements asked for in the same tick go to D1 as one batch: a page's
 * Promise.all of reads is one query against the Free plan's 50 a request. A
 * failed batch is retried statement by statement, so one bad read fails alone.
 */
type Pending = { statement: D1Statement; resolve: (rows: Record<string, unknown>[]) => void; reject: (error: unknown) => void };
const queued = new WeakMap<D1Database, Pending[]>();

function flush(db: D1Database, items: Pending[]) {
  db.batch(items.map((item) => item.statement)).then(
    (results) => items.forEach((item, at) => item.resolve(results[at]?.results ?? [])),
    () => {
      for (const item of items) db.batch([item.statement]).then((results) => item.resolve(results[0]?.results ?? []), item.reject);
    },
  );
}

function query(db: D1Database, sql: string, args: unknown[]): Promise<Record<string, unknown>[]> {
  return new Promise((resolve, reject) => {
    let items = queued.get(db);
    if (!items) {
      items = [];
      queued.set(db, items);
      queueMicrotask(() => {
        const due = queued.get(db) ?? [];
        queued.delete(db);
        flush(db, due);
      });
    }
    items.push({ statement: db.prepare(sql).bind(...args), resolve, reject });
  });
}

/**
 * Who is reading: `null` when nobody with access is signed in (RLS's empty
 * answer), else whether ratings may be read. The service role reads as a
 * non-admin: shared caches carry no rating (lib/home-cache.ts).
 */
export type Reading = () => Promise<{ admin: boolean } | null>;

/** The parts of a TableQuery plan read here (lib/db/table-query.mjs builds it). */
type Plan = { count: boolean; filters: { op: string; column?: string; value?: unknown }[] };

function executor(source: Source, reading: Reading) {
  return async (plan: Plan) => {
    const reader = await reading();
    if (!reader) return { rows: [], count: plan.count ? 0 : null };
    if (source.kind === "object") {
      const market = plan.filters.find((node) => node.op === "eq" && node.column === "market");
      if (!market) throw new UnsupportedQuery(`${source.table}: a live object is read for one market`);
      return evaluate(plan, (await readLiveObject(String(market.value), source.object)) ?? []);
    }
    const hide = source.gated && !reader.admin ? (column: string) => column === "*" || isRatingField(column) : () => false;
    const db = binding(source.database);
    const { data, count } = compile(plan, source.from, hide);
    const [rows, counted] = await Promise.all([
      data ? query(db, data.sql, data.args) : Promise.resolve([]),
      count ? query(db, count.sql, count.args) : Promise.resolve(null),
    ]);
    return { rows: rows.map((row) => decode(row, BOOLEANS)), count: counted ? Number(counted[0]?.n ?? 0) : null };
  };
}

/** `client`, its `from` answering moved tables from D1 or R2 as `reading` allows. */
export function withMarketTables<T extends { from: (relation: string) => unknown }>(client: T, reading: Reading): T {
  const supabaseFrom = client.from.bind(client);
  client.from = ((relation: string) => {
    const source = routed(relation);
    return source ? new TableQuery(executor(source, reading)) : supabaseFrom(relation);
  }) as T["from"];
  return client;
}
