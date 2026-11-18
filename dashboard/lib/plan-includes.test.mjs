import assert from "node:assert/strict";
import test from "node:test";

import { PLAN_INCLUDES } from "./plan-includes.mjs";

test("the plan list is 5-8 lines, each a feature and one fact", () => {
  assert.ok(PLAN_INCLUDES.length >= 5 && PLAN_INCLUDES.length <= 8);
  for (const [name, fact] of PLAN_INCLUDES) assert.ok(name && fact);
});

test("the plan list never sells what only an admin sees, or advice", () => {
  const text = PLAN_INCLUDES.flat().join(" ").toLowerCase();
  for (const word of ["rating", "buy", "sell", "recommend", "advice", "verdict", "returns", "model"]) {
    assert.ok(!new RegExp(`\\b${word}`).test(text), word);
  }
});
