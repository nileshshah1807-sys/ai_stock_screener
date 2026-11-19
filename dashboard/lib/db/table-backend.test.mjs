import assert from "node:assert/strict";
import test from "node:test";

import { readsOffSupabase } from "./table-backend.mjs";

test("TABLE_BACKEND moves the tables it names", () => {
  assert.equal(readsOffSupabase("", "market_events"), false);
  assert.equal(readsOffSupabase("supabase", "market_events"), false);
  assert.equal(readsOffSupabase("d1", "market_events"), true);
  assert.equal(readsOffSupabase("valuation_basis, market_events", "market_events"), true);
  assert.equal(readsOffSupabase("valuation_basis", "market_events"), false);
});

test("the concall feed is read from D1 whatever TABLE_BACKEND says: its Supabase copy is frozen", () => {
  for (const setting of ["", "supabase", "valuation_basis", "d1"]) assert.equal(readsOffSupabase(setting, "concall_feed"), true, setting);
});
