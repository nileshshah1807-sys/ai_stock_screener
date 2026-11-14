import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { SAVED_VIEWS_MAX, cleanViewQuery, legacyImportRows, unsentViews } from "./saved-views.mjs";

const MARKETS = ["NSE", "US"];

const SQL = readFileSync(new URL("../../storage/saved_views_schema.sql", import.meta.url), "utf8");

test("the schema's trigger caps at the dashboard's number", () => {
  assert.match(SQL, new RegExp(`market = new\\.market\\) >= ${SAVED_VIEWS_MAX} then`));
});

test("the cap also holds when an update moves a view to another market", () => {
  assert.match(SQL, /before insert or update of market on saved_views/);
  assert.match(SQL, /tg_op = 'UPDATE' and new\.market = old\.market then\s+return new;/);
});

test("browser views move to every market, once by name, and drop empties", () => {
  const { rows } = legacyImportRows(
    [
      { label: " Banks ", query: "sector=Banks" },
      { label: "banks", query: "sector=Banks&sort=pe" },
      { label: "Empty", query: "page=2" },
      { label: "", query: "sort=pe" },
    ],
    { US: ["BANKS"] },
    MARKETS,
  );
  assert.deepEqual(rows, [{ market: "NSE", name: "banks", query: "sector=Banks&sort=pe" }]);
});

test("the import never takes a market past the cap", () => {
  const local = Array.from({ length: 10 }, (_, at) => ({ label: `v${at}`, query: `sort=c${at}` }));
  const full = Array.from({ length: SAVED_VIEWS_MAX - 3 }, (_, at) => `old${at}`);
  const { rows, notMoved } = legacyImportRows(local, { NSE: full }, MARKETS);
  assert.equal(rows.filter((row) => row.market === "NSE").length, 3);
  assert.equal(rows.filter((row) => row.market === "US").length, 10);
  assert.equal(notMoved, 7);
});

test("the import reads at most the cap and drops oversized entries unparsed", () => {
  const local = Array.from({ length: SAVED_VIEWS_MAX + 5 }, (_, at) => ({ label: `v${at}`, query: `sort=c${at}` }));
  local[0] = { label: "x".repeat(61), query: "sort=pe" };
  local[1] = { label: "Long", query: `sort=${"x".repeat(2000)}` };
  const { rows, notMoved } = legacyImportRows(local, {}, ["NSE"]);
  assert.equal(rows.length, SAVED_VIEWS_MAX - 2);
  assert.equal(notMoved, 0);
  assert.ok(!rows.some((row) => row.name === `v${SAVED_VIEWS_MAX}`));
});

test("after an import only the views that were sent leave the browser", () => {
  const sent = [{ id: "1", label: "a", query: "sort=a" }];
  const current = [...sent, { id: "2", label: "saved meanwhile", query: "sort=b" }];
  assert.deepEqual(unsentViews(current, sent), [current[1]]);
});

test("a stored query keeps only the keys a view owns", () => {
  assert.equal(cleanViewQuery("sort=pe&page=3&evil=1&w=abc"), "sort=pe&w=abc");
  assert.equal(cleanViewQuery(`q=${"x".repeat(2100)}`), "");
});
