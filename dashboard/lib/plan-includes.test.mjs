import assert from "node:assert/strict";
import test from "node:test";

import { PLAN_INCLUDES, PLAN_INCLUDES_HEADING, PRICING_LEAD } from "./plan-includes.mjs";

test("the plan list is 5-8 lines, each a feature and one fact", () => {
  assert.ok(PLAN_INCLUDES.length >= 5 && PLAN_INCLUDES.length <= 8);
  for (const [name, fact] of PLAN_INCLUDES) assert.ok(name && fact);
});

// "rank" is allowed: Your score ranks by the viewer's own weights, not the model's.
const FORBIDDEN = ["rating", "buy", "sell", "recommend", "advice", "verdict", "returns", "model", "signal", "pick", "top", "best", "outperform", "target", "predict"];

test("the pricing copy never sells what only an admin sees, or advice", () => {
  const text = [PRICING_LEAD, PLAN_INCLUDES_HEADING, ...PLAN_INCLUDES.flat()].join(" ").toLowerCase();
  for (const word of FORBIDDEN) assert.ok(!new RegExp(`\\b${word}`).test(text), word);
});
