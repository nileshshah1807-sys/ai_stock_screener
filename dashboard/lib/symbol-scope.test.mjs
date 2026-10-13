import assert from "node:assert/strict";
import { test } from "node:test";

import { PUSH_DOWN_MAX, readForSymbols } from "./symbol-scope.mjs";

/** A feed of `count` rows, newest first, whose symbols cycle through `symbols`. */
function feed(count, symbols) {
  const rows = Array.from({ length: count }, (_, index) => ({
    id: index,
    symbol: symbols[index % symbols.length],
  }));
  const calls = [];
  const read = async (pushed, from, to) => {
    calls.push({ pushed, from, to });
    const scoped = pushed ? rows.filter((row) => pushed.includes(row.symbol)) : rows;
    return { data: scoped.slice(from, to + 1), error: null };
  };
  return { read, calls };
}

const many = (count) => Array.from({ length: count }, (_, index) => `S${index}`);

test("no restriction is one read of the newest rows", async () => {
  const { read, calls } = feed(50, ["A", "B"]);
  const { rows } = await readForSymbols(null, 10, read);
  assert.equal(rows.length, 10);
  assert.deepEqual(calls, [{ pushed: null, from: 0, to: 9 }]);
});

test("an empty set matches nothing and reads nothing", async () => {
  const { read, calls } = feed(50, ["A"]);
  assert.deepEqual(await readForSymbols([], 10, read), { rows: [], error: null });
  assert.equal(calls.length, 0);
});

test("a small set goes into the query", async () => {
  const { read, calls } = feed(50, ["A", "B"]);
  const { rows } = await readForSymbols(["B"], 10, read);
  assert.equal(rows.length, 10);
  assert.ok(rows.every((row) => row.symbol === "B"));
  assert.deepEqual(calls[0].pushed, ["B"]);
});

test("a large set is filtered here, across windows, newest first", async () => {
  const wanted = many(PUSH_DOWN_MAX + 1);
  // One row in four belongs to a wanted symbol.
  const { read, calls } = feed(2500, [wanted[0], "X", "Y", "Z"]);
  const { rows, error } = await readForSymbols(wanted, 300, read);
  assert.equal(error, null);
  assert.equal(rows.length, 300);
  assert.ok(rows.every((row) => row.symbol === wanted[0]));
  assert.deepEqual(rows.slice(0, 2).map((row) => row.id), [0, 4]);
  assert.ok(calls.every((call) => call.pushed === null));
  assert.deepEqual(calls.map((call) => call.from), [0, 1000]);
});

test("a large set stops at the end of the feed", async () => {
  const { read, calls } = feed(120, ["X"]);
  const { rows } = await readForSymbols(many(PUSH_DOWN_MAX + 1), 50, read);
  assert.deepEqual(rows, []);
  assert.equal(calls.length, 1);
});

test("a failed read reports its message", async () => {
  const failing = async () => ({ data: null, error: { message: "boom" } });
  assert.deepEqual(await readForSymbols(null, 10, failing), { rows: [], error: "boom" });
});
