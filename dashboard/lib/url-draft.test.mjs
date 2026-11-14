import assert from "node:assert/strict";
import test from "node:test";

import { formatWeights, parseWeights } from "./custom-score.mjs";
import { draftAfterUrlChange } from "./url-draft.mjs";

const text = [(url) => url, (draft) => draft.trim()];

test("a saved view's text replaces what the box held", () => {
  assert.equal(draftAfterUrlChange("infosys", "tata", ...text), "tata");
  assert.equal(draftAfterUrlChange("infosys", "", ...text), "", "a removed chip empties the box");
});

test("the debounce landing does not eat a trailing space mid-typing", () => {
  assert.equal(draftAfterUrlChange("tata ", "tata", ...text), "tata ");
});

test("a saved view's score mix moves the sliders", () => {
  const weights = [(url) => parseWeights(url) ?? {}, formatWeights];
  assert.deepEqual(draftAfterUrlChange({ q: 50, m: 50 }, "v100", ...weights), { v: 100 });
  const mine = { q: 50, m: 50, g: 0 };
  assert.equal(draftAfterUrlChange(mine, "q50.m50", ...weights), mine, "applying my own mix keeps my draft");
});
