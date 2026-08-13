import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("./queries.ts", import.meta.url), "utf8");

function functionSource(name, nextName) {
  const start = source.indexOf(`export async function ${name}`);
  const end = source.indexOf(`export async function ${nextName}`, start + 1);
  assert.notEqual(start, -1, `${name} must exist`);
  assert.notEqual(end, -1, `${nextName} must follow ${name}`);
  return source.slice(start, end);
}

test("run selectors exclude incomplete publisher reservations", () => {
  const latest = functionSource("getLatestRun", "getRecentRuns");
  const recent = functionSource("getRecentRuns", "getSnapshotPage");

  assert.match(latest, /\.gt\("row_count",\s*0\)/);
  assert.match(recent, /\.gt\("row_count",\s*0\)/);
});
