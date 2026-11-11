import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import test from "node:test";

/**
 * A loader handed to `sharedRead` / `cachedOr` / `homeCached` runs inside
 * `unstable_cache`, where Next refuses cookies(). The failure is thrown on a
 * cache MISS only, and React's cache() then remembers the rejected call for
 * the request, so the fallback rethrows and the page shows a server error
 * (Concalls, 11 Nov 2026). Such a loader may use only the client it is handed
 * (`db`): no session read, and nothing that reads one.
 */
const SESSION_READS = [
  /\bcookies\s*\(/,
  /\bheaders\s*\(/,
  /(?<!db \?\? \(await )\bcreateClient\s*\(/,
  /\bgetViewer\s*\(/,
  /\bisAdmin\s*\(/,
  /\brequireAccess\s*\(/,
  /\bgetLatestRun\s*\(/,
  /\bgetSearchIndex\s*\(/,
  /\brunCompanyNames\s*\(/,
  /\bgetWatchlists\s*\(/,
  /\bgetCompanyFacts\s*\(/,
];

const dir = new URL("./", import.meta.url);

/** The text of `function name` up to the next top-level closing brace. */
function body(source, name) {
  const start = source.search(new RegExp(`(?:async\\s+)?function\\s+${name}\\b`));
  if (start === -1) return null;
  const end = source.indexOf("\n}\n", start);
  return source.slice(start, end === -1 ? undefined : end);
}

for (const file of readdirSync(dir).filter((name) => /\.tsx?$/.test(name) && !/\.test\./.test(name))) {
  const source = readFileSync(new URL(file, dir), "utf8");
  // `sharedRead("x", market, 300, (db) => readX(...)` -- the named loader and its body.
  const named = [...source.matchAll(/(?:sharedRead|cachedOr)\s*\([^)]*?\(\s*db\s*\)\s*=>\s*(\w+)\s*\(/gs)].map((m) => m[1]);
  for (const name of new Set(named)) {
    test(`${file}: cached loader ${name} reads no session`, () => {
      const text = body(source, name);
      assert.ok(text, `${name} must be a function in ${file}`);
      for (const pattern of SESSION_READS) {
        // getResultFeed asks for company names only on a search, and getResultFeedShared never caches a search.
        if (name === "getResultFeed" && /runCompanyNames/.test(String(pattern))) continue;
        assert.doesNotMatch(text, pattern, `${name} runs inside the cache: ${pattern} is not allowed`);
      }
    });
  }
}

test("the guard finds the loaders it is meant to guard", () => {
  const found = readdirSync(dir)
    .filter((name) => /\.ts$/.test(name))
    .flatMap((file) => [...readFileSync(new URL(file, dir), "utf8").matchAll(/sharedRead\s*\(/g)]);
  assert.ok(found.length >= 5, "sharedRead callers disappeared; update this guard with them");
});
