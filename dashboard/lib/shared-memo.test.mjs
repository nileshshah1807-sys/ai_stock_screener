import assert from "node:assert/strict";
import { test } from "node:test";

import { freshValue } from "./shared-memo.mjs";

const NOW = Date.parse("2026-11-13T14:00:00Z");

test("a shared-cache entry within its revalidate window is served", () => {
  assert.deepEqual(freshValue({ at: NOW - 299_000, value: ["MMFL"] }, 300, NOW), ["MMFL"]);
});

// unstable_cache returns a stale entry as-is: a filter few viewers use kept
// hours-old calls until Reset hit the busy unfiltered key (13 Nov 2026).
test("a stale shared-cache entry is a miss, so the caller reads live", () => {
  assert.equal(freshValue({ at: NOW - 3 * 3600_000, value: ["old"] }, 300, NOW), undefined);
  assert.equal(freshValue(["written before entries were stamped"], 300, NOW), undefined);
  assert.equal(freshValue(undefined, 300, NOW), undefined);
});
