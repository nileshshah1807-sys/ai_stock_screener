import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

// The banner is about the screener ranking, so only the Screener page shows it.
test("the stale-ranking banner is rendered by the screener layout, not the app shell", () => {
  assert.doesNotMatch(read("../components/app-shell.tsx"), /FreshnessBanner/);
  assert.match(read("../app/(app)/[market]/(screener)/layout.tsx"), /<FreshnessBanner run=\{run\} \/>/);
});

test("the warning names the screener ranking and its run date", () => {
  const source = read("../components/freshness-banner.tsx");
  assert.match(source, /Screener ranking is from the/);
  assert.doesNotMatch(source, /normal weekend gap/);
});
