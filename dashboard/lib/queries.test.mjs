import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("./queries.ts", import.meta.url), "utf8");

/**
 * Offset of an exported query, whichever form it is declared in.
 *
 * Some of these are plain `export async function`, others are wrapped for
 * per-request memoisation as `export const x = cache(async ...)`. Matching both
 * keeps this test about the query's behaviour rather than its declaration
 * style, so adding or removing a wrapper does not silently stop checking it.
 */
function exportOffset(name) {
  const match = new RegExp(
    `export\\s+(?:async\\s+function\\s+${name}\\b|const\\s+${name}\\s*=)`,
  ).exec(source);
  return match ? match.index : -1;
}

function functionSource(name, nextName) {
  const start = exportOffset(name);
  const end = exportOffset(nextName);
  assert.notEqual(start, -1, `${name} must exist`);
  assert.notEqual(end, -1, `${nextName} must exist`);
  assert.ok(end > start, `${nextName} must follow ${name}`);
  return source.slice(start, end);
}

test("run selectors exclude incomplete publisher reservations", () => {
  const latest = functionSource("getLatestRun", "getRecentRuns");
  const recent = functionSource("getRecentRuns", "getSnapshotPage");

  assert.match(latest, /\.gt\("row_count",\s*0\)/);
  assert.match(recent, /\.gt\("row_count",\s*0\)/);
});

test("universe-wide reads page past the PostgREST row cap", () => {
  // getSectors and getSearchIndex both read the whole universe. Whether they
  // walk chunks sequentially or fan them out, every chunk must be bounded by
  // FETCH_CHUNK or the read silently truncates at PostgREST's default limit.
  const sectors = functionSource("getSectors", "getMovers");
  const searchIndex = functionSource("getSearchIndex", "runUsesFactorModel");

  for (const [name, body] of [
    ["getSectors", sectors],
    ["getSearchIndex", searchIndex],
  ]) {
    assert.match(
      body,
      /\.range\(\s*offset,\s*offset \+ FETCH_CHUNK - 1\s*\)/,
      `${name} must request bounded chunks`,
    );
  }
});
