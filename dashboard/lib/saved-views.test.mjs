import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { SAVED_VIEWS_MAX, cleanViewQuery, legacyImportRows } from "./saved-views.mjs";

const MARKETS = ["NSE", "US"];

test("the schema's trigger caps at the dashboard's number", () => {
  const sql = readFileSync(new URL("../../storage/saved_views_schema.sql", import.meta.url), "utf8");
  assert.match(sql, new RegExp(`market = new\\.market\\) >= ${SAVED_VIEWS_MAX} then`));
});

test("browser views move to every market, once by name, and drop empties", () => {
  const rows = legacyImportRows(
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
  const rows = legacyImportRows(local, { NSE: full }, MARKETS);
  assert.equal(rows.filter((row) => row.market === "NSE").length, 3);
  assert.equal(rows.filter((row) => row.market === "US").length, 10);
});

test("a stored query keeps only the keys a view owns", () => {
  assert.equal(cleanViewQuery("sort=pe&page=3&evil=1&w=abc"), "sort=pe&w=abc");
  assert.equal(cleanViewQuery(`q=${"x".repeat(2100)}`), "");
});
