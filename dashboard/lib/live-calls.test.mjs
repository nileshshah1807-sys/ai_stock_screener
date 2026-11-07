import assert from "node:assert/strict";
import test from "node:test";

import { clock, mergeLines, sampleLines } from "./live-calls.mjs";

test("mergeLines keeps each seq once, in order", () => {
  const merged = mergeLines(
    [{ seq: 1, text: "a" }, { seq: 2, text: "b" }],
    [{ seq: 2, text: "b" }, { seq: 3, text: "c" }, { seq: null, text: "x" }],
  );
  assert.deepEqual(merged.map((l) => l.seq), [1, 2, 3]);
});

test("clock reads minutes and hours", () => {
  assert.equal(clock(247.6), "4:07");
  assert.equal(clock(3729), "1:02:09");
  assert.equal(clock(null), "0:00");
});

test("sampleLines resumes after the cursor", () => {
  assert.equal(sampleLines(0).length, 1);
  assert.deepEqual(sampleLines(12, 2).map((l) => l.seq), [3]);
  assert.equal(sampleLines(600).at(-1).seq, 121);
});
