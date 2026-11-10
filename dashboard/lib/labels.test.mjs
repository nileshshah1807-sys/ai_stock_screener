import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

import { NON_ADMIN_TABLES } from "./labels.ts";
import { publicText } from "./ratings.mjs";

// A rating word, an eligibility mention or a cap: none may reach a non-admin.
const LEAK = /\b(STRONG BUY|BUY|HOLD|REDUCE|SELL)\b|eligib|\bcaps?\b|\bcapped\b/i;
// Exact strings known not to be a leak (add with the reason).
const ALLOWED = new Set([
  // "blend-eligible" is the DCF blend into the score, not a rating eligibility.
  "Based on reported positive cash flow, so this result is blend-eligible and contributes to the score.",
]);

test("no copy table meaning leaks a rating, eligibility or cap to a non-admin", () => {
  for (const [table, entries] of Object.entries(NON_ADMIN_TABLES)) {
    for (const [key, { meaning }] of Object.entries(entries)) {
      const shown = publicText(false, meaning);
      assert.ok(ALLOWED.has(shown) || !LEAK.test(shown), `${table}.${key} leaks: ${shown}`);
    }
  }
});

function sources(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(name) ? [path] : [];
  });
}

test("every use of those tables' meanings goes through publicText", () => {
  const use = /(dcfStatus|dataQuality|marketRegime)\([^)]*\)\.meaning|\b(dcf|regime)\.meaning/;
  for (const file of ["app", "components"].flatMap((dir) => sources(dir))) {
    readFileSync(file, "utf8").split("\n").forEach((line, i) => {
      if (use.test(line)) assert.match(line, /publicText\(/, `${file}:${i + 1} shows a meaning without publicText`);
    });
  }
});
