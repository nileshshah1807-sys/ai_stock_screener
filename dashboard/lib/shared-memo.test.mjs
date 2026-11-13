import assert from "node:assert/strict";
import { test } from "node:test";

import { cacheWindow } from "./shared-memo.mjs";

const NOW = Date.parse("2026-11-13T14:00:00Z");
const KEY = "concalls:NSE:abc";

test("one key's reads share a window, and a later window is a new key", () => {
  const windows = new Set();
  for (let ms = 0; ms < 600_000; ms += 1_000) windows.add(cacheWindow(300, KEY, NOW + ms));
  // Ten minutes span two or three windows of five: never one entry served past five minutes.
  assert.ok(windows.size >= 2 && windows.size <= 3, String(windows.size));
  assert.equal(cacheWindow(300, KEY, NOW), cacheWindow(300, KEY, NOW));
});

// unstable_cache returns a stale entry as-is: a filter few viewers used kept
// hours-old calls until Reset hit the busy unfiltered key (13 Nov 2026).
test("an entry hours old is never the current key", () => {
  assert.notEqual(cacheWindow(300, KEY, NOW), cacheWindow(300, KEY, NOW + 3 * 3600_000));
});

test("different keys change window at different moments", () => {
  const boundary = (key) => {
    const start = cacheWindow(300, key, NOW);
    let ms = 0;
    while (cacheWindow(300, key, NOW + ms) === start) ms += 1_000;
    return ms;
  };
  assert.notEqual(boundary("concalls:NSE:abc"), boundary("events:NSE:all"));
});
