import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { test } from "node:test";

import { isAdminOnlyField, isRatingField, withoutRatings } from "../ratings.mjs";
import { SNAPSHOT_COLUMNS } from "./d1-views.mjs";
import { compile, readRow, splitExtra, TableQuery } from "./table-query.mjs";

const DDL = readFileSync(new URL("../../../storage/d1/screener_snapshot.sql", import.meta.url), "utf8");
const BOOLEANS = new Set(["buy_eligible", "is_sme"]);

test("SNAPSHOT_COLUMNS are the D1 table's real columns", () => {
  const table = DDL.slice(DDL.indexOf("CREATE TABLE"), DDL.indexOf("PRIMARY KEY"));
  const columns = [...table.matchAll(/^\s+"([a-z0-9_]+)"/gm)].map((m) => m[1]).filter((c) => c !== "extra");
  assert.deepEqual(columns, SNAPSHOT_COLUMNS);
});

function database() {
  const db = new DatabaseSync(":memory:");
  db.exec(DDL);
  const extra = { investment_rating: "BUY", score_rank: 3, research_score_basis: "q+g", value_quality_cap_applied: true, adx_14: 22 };
  db.prepare(
    `INSERT INTO screener_snapshot (market, run_date, symbol, company, rating, buy_eligible, investment_rank, final_score, primary_gate, quality_score, is_sme, extra)
     VALUES ('NSE', '2026-11-13', 'TCS', 'Tata', 'BUY', 1, 4, 71.5, 'none', 80, 0, ?)`,
  ).run(JSON.stringify(extra));
  return db;
}

/** The repository's executor, minus the bindings: split, compile with the gated hide, read rows. */
const reader = (db, admin) => () =>
  new TableQuery(async (plan) => {
    const split = splitExtra(plan, SNAPSHOT_COLUMNS);
    const hide = admin ? () => false : (column) => column === "*" || isRatingField(column);
    const { data } = compile(split.plan, '"screener_snapshot"', hide);
    const rows = db.prepare(data.sql).all(...data.args).map((row) => ({ ...row }));
    return { rows: rows.map((row) => readRow(row, BOOLEANS, split.picks, admin ? null : withoutRatings)), count: null };
  });

test("a non-admin's D1 snapshot row carries no rating or verdict, from real columns or extra", async () => {
  const db = database();
  for (const select of ["*", "symbol, rating, final_score, investment_rating, score_rank, research_score_basis, value_quality_cap_applied, adx_14"]) {
    const { data, error } = await reader(db, false)().select(select).eq("market", "NSE").maybeSingle();
    assert.equal(error, null);
    for (const [key, value] of Object.entries(data)) if (isAdminOnlyField(key)) assert.equal(value, null, `${select}: ${key}`);
    assert.equal(data.adx_14, 22);
    assert.equal(data.symbol, "TCS");
    assert.ok(!("extra" in data));
    for (const key of ["research_score_basis", "value_quality_cap_applied", "investment_rating"]) assert.ok(key in data && data[key] === null, key);
  }
  const all = (await reader(db, false)().select("*").maybeSingle()).data;
  assert.equal(all.quality_score, 80);
  assert.equal(all.is_sme, false);
});

test("an admin reads extra's fields merged into the row, booleans decoded", async () => {
  const { data } = await reader(database(), true)().select("symbol, rating, buy_eligible, investment_rating, adx_14, nope").single();
  assert.deepEqual(data, { symbol: "TCS", rating: "BUY", buy_eligible: true, investment_rating: "BUY", adx_14: 22, nope: null });
});

test("filtering or sorting on a key of extra is refused, not guessed", async () => {
  const db = database();
  assert.equal((await reader(db, true)().select("symbol").eq("adx_14", 22)).error.code, "UNSUPPORTED");
  assert.equal((await reader(db, true)().select("symbol").order("adx_14")).error.code, "UNSUPPORTED");
});
