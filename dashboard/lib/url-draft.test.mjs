import assert from "node:assert/strict";
import test from "node:test";

import { formatWeights, parseWeights } from "./custom-score.mjs";
import { asText, draftAfterUrlChange, trimmed } from "./url-draft.mjs";

const text = [asText, trimmed];
const after = (...args) => draftAfterUrlChange(...args).draft;

test("a saved view's text replaces what the box held", () => {
  assert.equal(after("infosys", "tata", ...text), "tata");
  assert.equal(after("infosys", "", ...text), "", "a removed chip empties the box");
});

test("the debounce landing does not eat a trailing space mid-typing", () => {
  assert.equal(after("tata ", "tata", ...text), "tata ");
});

test("the box's own earlier push landing late keeps what was typed since", () => {
  const landed = draftAfterUrlChange("abc", "ab", ...text, ["ab"]);
  assert.deepEqual(landed, { draft: "abc", pending: [] });
  assert.deepEqual(draftAfterUrlChange("abcd", "ab", ...text, ["ab", "abc"]), { draft: "abcd", pending: ["abc"] }, "a later push still waits");
  assert.deepEqual(draftAfterUrlChange("abc", "tata", ...text, ["ab"]), { draft: "tata", pending: [] }, "anything else is followed and the pushes are dropped");
});

test("a saved view's score mix moves the sliders", () => {
  const weights = [(url) => parseWeights(url) ?? {}, formatWeights];
  assert.deepEqual(after({ q: 50, m: 50 }, "v100", ...weights), { v: 100 });
  const mine = { q: 50, m: 50, g: 0 };
  assert.equal(after(mine, "q50.m50", ...weights), mine, "applying my own mix keeps my draft");
});
