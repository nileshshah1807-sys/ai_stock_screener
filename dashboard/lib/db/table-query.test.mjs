import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { test } from "node:test";

import { RESULT_FEED } from "./d1-views.mjs";
import { bound, compile, decode, evaluate, TableQuery } from "./table-query.mjs";

// Shaped as storage/d1/core.sql (PR #344), trimmed to the columns used here.
const DDL = `
CREATE TABLE quarterly_filings (
  market TEXT NOT NULL, symbol TEXT NOT NULL, period_end TEXT NOT NULL, is_consolidated INTEGER NOT NULL,
  filed_at TEXT NOT NULL, broadcast_at TEXT, lines TEXT NOT NULL, company TEXT,
  PRIMARY KEY (market, symbol, period_end, is_consolidated)) WITHOUT ROWID;
CREATE TABLE screener_history (
  observed_on TEXT NOT NULL, symbol TEXT NOT NULL, market TEXT NOT NULL, rating TEXT, investment_rank INTEGER, current_price REAL,
  PRIMARY KEY (observed_on, symbol, market)) WITHOUT ROWID;`;

const FILINGS = [
  ["NSE", "TCS", "2026-09-30", 1, "2026-10-10T10:00:00+00:00", "2026-10-09T12:00:00+00:00", { revenue: 10, period_days: 92 }, "Tata Consultancy"],
  ["NSE", "TCS", "2026-09-30", 0, "2026-10-10T10:00:00+00:00", null, { revenue: 8 }, "Tata Consultancy"],
  ["NSE", "INFY", "2026-09-30", 0, "2026-10-12T10:00:00+00:00", null, { revenue: null, net_profit: null }, "Infosys"],
  ["NSE", "ANAWIL", "2026-09-30", 0, "2026-11-01T10:00:00+00:00", null, { cumulative: { revenue: 5 }, period_days: 182 }, null],
  ["US", "TCS", "2026-09-27", 0, "2026-11-02T10:00:00+00:00", null, { revenue: 3 }, "The Container Store"],
];

function database() {
  const db = new DatabaseSync(":memory:");
  db.exec(DDL);
  const insert = db.prepare("INSERT INTO quarterly_filings VALUES (?, ?, ?, ?, ?, ?, ?, ?)");
  for (const row of FILINGS) insert.run(...row.slice(0, 6), JSON.stringify(row[6]), row[7]);
  const history = db.prepare("INSERT INTO screener_history VALUES (?, ?, ?, ?, ?, ?)");
  history.run("2026-11-13", "TCS", "NSE", "BUY", 3, 4100.5);
  history.run("2026-11-12", "TCS", "NSE", "HOLD", 9, 4000);
  history.run("2026-11-13", "INFY", "NSE", null, null, 1500);
  return db;
}

const BOOLEANS = new Set(["is_consolidated", "has_consolidated", "has_standalone"]);

/** A TableQuery over SQLite, as market-repository runs one over D1. */
function sqlite(db, from, hide) {
  return () =>
    new TableQuery(async (plan) => {
      const { data, count } = compile(plan, from, hide);
      const rows = data ? db.prepare(data.sql).all(...data.args).map((row) => decode({ ...row }, BOOLEANS)) : [];
      return { rows, count: count ? Number(db.prepare(count.sql).get(...count.args).n) : null };
    });
}

test("filters, order, range and count read as PostgREST answers them", async () => {
  const from = sqlite(database(), '"quarterly_filings"');
  const { data, count, error } = await from()
    .select("symbol, is_consolidated, revenue:lines->revenue, half:lines->cumulative->revenue", { count: "exact" })
    .eq("market", "NSE")
    .in("period_end", ["2026-09-30"])
    .order("symbol", { ascending: false })
    .order("is_consolidated")
    .range(0, 1);
  assert.equal(error, null);
  assert.equal(count, 4);
  assert.deepEqual(data, [
    { symbol: "TCS", is_consolidated: false, revenue: 8, half: null },
    { symbol: "TCS", is_consolidated: true, revenue: 10, half: null },
  ]);
});

test("or strings: ilike, quoted in-lists, nested and, not", async () => {
  const from = sqlite(database(), '"quarterly_filings"');
  const { data } = await from()
    .select("symbol")
    .eq("market", "NSE")
    .or('symbol.ilike.*tc*,company.ilike.*infos*,symbol.in.("ANAWIL")')
    .or("and(period_end.gt.2026-06-30,period_end.lte.2026-09-30)")
    .not("company", "is", null)
    .order("symbol");
  assert.deepEqual(data.map((row) => row.symbol), ["INFY", "TCS", "TCS"]);
});

test("maybeSingle: null for none, an error for several; head counts only", async () => {
  const from = sqlite(database(), '"quarterly_filings"');
  assert.equal((await from().select("symbol").eq("symbol", "NONE").maybeSingle()).data, null);
  const several = await from().select("symbol").eq("symbol", "TCS").maybeSingle();
  assert.equal(several.data, null);
  assert.equal(several.error.code, "PGRST116");
  const head = await from().select("symbol", { count: "exact", head: true }).eq("market", "US");
  assert.deepEqual([head.data, head.count], [null, 1]);
});

test("a hidden column is null wherever it appears, so a filter on it cannot reveal it", async () => {
  const hide = (column) => column === "*" || column === "rating";
  const from = sqlite(database(), '"screener_history"', hide);
  const { data } = await from()
    .select("symbol, rating, investment_rank")
    .eq("market", "NSE")
    .eq("symbol", "TCS")
    .order("observed_on", { ascending: false });
  assert.deepEqual(data, [
    { symbol: "TCS", rating: null, investment_rank: 3 },
    { symbol: "TCS", rating: null, investment_rank: 9 },
  ]);
  assert.deepEqual((await from().select("symbol").in("rating", ["BUY"])).data, []);
  assert.match((await from().select("*")).error.message, /name the columns/);
  assert.equal((await from().select("symbol, rating::text")).error.code, "UNSUPPORTED");
});

test("the result feed view: a company's quarter once, empty filings left out, both bases flagged", async () => {
  const from = sqlite(database(), RESULT_FEED);
  const { data } = await from()
    .select("symbol, announced_at, has_consolidated, has_standalone, period_days")
    .eq("market", "NSE")
    .eq("period_end", "2026-09-30")
    .order("announced_at", { ascending: false, nullsFirst: false });
  assert.deepEqual(data, [
    { symbol: "ANAWIL", announced_at: "2026-11-01T10:00:00+00:00", has_consolidated: false, has_standalone: true, period_days: 182 },
    { symbol: "TCS", announced_at: "2026-10-09T12:00:00+00:00", has_consolidated: true, has_standalone: true, period_days: 92 },
  ]);
});

test("the view's market filter reaches the table's key, not a full scan", () => {
  const db = database();
  const plan = { columns: "symbol", filters: [{ op: "eq", column: "market", value: "NSE" }], orders: [], offset: 0, limit: null, count: false, head: false };
  const { data } = compile(plan, RESULT_FEED);
  const steps = db.prepare(`EXPLAIN QUERY PLAN ${data.sql}`).all(...data.args).map((row) => row.detail).join(" | ");
  assert.match(steps, /SEARCH quarterly_filings USING PRIMARY KEY \(market=\?\)/, steps);
});

test("a timestamp filter is compared in UTC, as D1 holds it", () => {
  assert.equal(bound("2026-11-14T00:00:00+05:30"), "2026-11-13T18:30:00");
  assert.equal(bound("2026-11-14"), "2026-11-14");
  assert.equal(bound(true), 1);
});

test("in memory, a plan answers as SQLite does", async () => {
  const db = database();
  const rows = db.prepare("SELECT market, symbol, period_end, company FROM quarterly_filings").all().map((row) => ({ ...row }));
  const memory = () => new TableQuery(async (plan) => evaluate(plan, rows));
  const fromSql = sqlite(db, '"quarterly_filings"');
  const build = (query) =>
    query
      .select("symbol, company", { count: "exact" })
      .eq("market", "NSE")
      .or("company.ilike.*tata*,company.is.null")
      .order("company", { ascending: false })
      .order("symbol")
      .range(1, 5);
  assert.deepEqual(await build(memory()), await build(fromSql()));
});
