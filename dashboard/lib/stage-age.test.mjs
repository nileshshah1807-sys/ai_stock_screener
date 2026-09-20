import assert from "node:assert/strict";
import test from "node:test";

import { stageAge } from "./stage-age.mjs";

test("an advancing stock reports the age of its advance, not of the label", () => {
  // The reported bug: a months-long advance dipped under the 50-day average,
  // which restarted days_in_stage, and the grid showed "S2 0d".
  assert.deepEqual(
    stageAge({ stage: "Stage 2", days_in_stage: 0, advance_age_days: 391 }),
    { days: 391, censored: false },
  );
  assert.deepEqual(
    stageAge({ stage: "S2 Candidate", days_in_stage: 3, advance_age_days: 128 }),
    { days: 128, censored: false },
  );
});

test("a censored advance is flagged as a floor", () => {
  assert.deepEqual(
    stageAge({
      stage: "Stage 2",
      days_in_stage: 12,
      advance_age_days: 406,
      advance_age_censored: true,
    }),
    { days: 406, censored: true },
  );
});

test("a non-advancing stage still reports days in that stage", () => {
  for (const stage of ["Stage 1", "Stage 3", "Stage 4"]) {
    assert.deepEqual(
      stageAge({ stage, days_in_stage: 42, advance_age_days: null }),
      { days: 42, censored: false },
      stage,
    );
  }
});

test("an advancing stage with no advance age falls back to days in stage", () => {
  assert.deepEqual(
    stageAge({ stage: "Stage 2", days_in_stage: 7, advance_age_days: null }),
    { days: 7, censored: false },
  );
});

test("nothing to show when neither figure is published", () => {
  assert.equal(stageAge({ stage: "Stage 2", days_in_stage: null }), null);
  assert.equal(stageAge({ stage: null, days_in_stage: null }), null);
});

test("zero is a real age, not a missing one", () => {
  assert.deepEqual(stageAge({ stage: "Stage 1", days_in_stage: 0 }), {
    days: 0,
    censored: false,
  });
});
