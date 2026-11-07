import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import test from "node:test";

/**
 * billing_schema.sql revokes every grant on `subscriptions` and re-grants its own
 * list, so re-applying it alone must restore everything the dashboard reads as the
 * signed-in user. (Re-applying it once dropped plan_amount_paise and trial_denied_at
 * and every subscriber's /account showed "No plan".)
 */
const dir = new URL("../../storage/", import.meta.url);
const list = (text) => text.split(",").map((c) => c.trim()).filter(Boolean);

function billingGrants() {
  const sql = readFileSync(new URL("billing_schema.sql", dir), "utf8");
  const grants = [...sql.matchAll(/grant select \(([^)]*)\)\s+on subscriptions to authenticated/gi)];
  assert.ok(grants.length, "billing_schema.sql grants select on subscriptions");
  return new Set(list(grants.at(-1)[1]));
}

test("every column getSubscription reads is granted by billing_schema.sql alone", () => {
  const ts = readFileSync(new URL("../lib/plans.ts", import.meta.url), "utf8");
  const at = ts.indexOf('.from("subscriptions")');
  const columns = list(/\.select\("([^"]+)"\)/.exec(ts.slice(at))[1]);
  assert.ok(columns.length > 5);
  const granted = billingGrants();
  for (const column of columns) assert.ok(granted.has(column), `${column} must be granted in billing_schema.sql`);
});

test("every column another schema file grants on subscriptions is also granted by billing_schema.sql", () => {
  const granted = billingGrants();
  for (const file of readdirSync(dir).filter((f) => f.endsWith(".sql") && f !== "billing_schema.sql")) {
    const sql = readFileSync(new URL(file, dir), "utf8");
    for (const m of sql.matchAll(/grant select \(([^)]*)\)\s+on subscriptions to authenticated/gi)) {
      for (const column of list(m[1])) assert.ok(granted.has(column), `${file} grants ${column}: billing_schema.sql must too`);
    }
  }
});

test("billing_schema.sql creates the columns it grants", () => {
  const sql = readFileSync(new URL("billing_schema.sql", dir), "utf8");
  for (const column of ["plan_amount_paise", "trial_denied_at", "offer_applied"]) {
    assert.match(sql, new RegExp(`add column if not exists ${column}\\b`));
  }
});
