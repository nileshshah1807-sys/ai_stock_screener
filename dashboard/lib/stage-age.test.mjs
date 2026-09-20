import assert from "node:assert/strict";
import test from "node:test";

import { daysBetween, stageAge } from "./stage-age.mjs";

const BAR = "2026-09-18";

test("an advancing stock reports days since it entered Stage 2", () => {
  // CAPLIPOINT's shape: the label flipped back to Stage 2 today, so
  // days_in_stage is 0, but the advance entered Stage 2 on 30 Jul.
  assert.deepEqual(
    stageAge({
      stage: "Stage 2",
      days_in_stage: 0,
      advance_age_days: 100,
      stage2_entry_date: "2026-07-30",
      price_bar_as_of: BAR,
    }),
    { days: 50, censored: false, basis: "stage2" },
  );
});

test("a pullback to S2 Candidate keeps counting from the same Stage 2 entry", () => {
  // The stock is mid-pullback: the advance has not ended, so the answer to
  // "how long advancing?" must not change just because the label did.
  assert.deepEqual(
    stageAge({
      stage: "S2 Candidate",
      days_in_stage: 3,
      advance_age_days: 100,
      stage2_entry_date: "2026-07-30",
      price_bar_as_of: BAR,
    }),
    { days: 50, censored: false, basis: "stage2" },
  );
});

test("an entry date that is only an upper bound is flagged as a floor", () => {
  assert.deepEqual(
    stageAge({
      stage: "Stage 2",
      days_in_stage: 12,
      advance_age_days: 406,
      stage2_entry_date: "2025-01-01",
      stage2_entry_censored: true,
      price_bar_as_of: BAR,
    }),
    { days: 625, censored: true, basis: "stage2" },
  );
});

test("advancing without a Stage 2 entry falls back to the advance's age", () => {
  // S2 Candidate that never reached the full stack in the available history.
  assert.deepEqual(
    stageAge({
      stage: "S2 Candidate",
      days_in_stage: 9,
      advance_age_days: 21,
      stage2_entry_date: null,
      price_bar_as_of: BAR,
    }),
    { days: 21, censored: false, basis: "advance" },
  );
});

test("a non-advancing stage reports days on that label", () => {
  for (const stage of ["Stage 1", "Stage 3", "Stage 4"]) {
    assert.deepEqual(
      stageAge({
        stage,
        days_in_stage: 42,
        advance_age_days: null,
        // An old advance's entry date is still published; it must not be used
        // for a stock that has since broken down.
        stage2_entry_date: "2025-03-01",
        price_bar_as_of: BAR,
      }),
      { days: 42, censored: false, basis: "label" },
      stage,
    );
  }
});

test("nothing to show when no figure is published", () => {
  assert.equal(stageAge({ stage: "Stage 2", days_in_stage: null }), null);
  assert.equal(stageAge({ stage: null, days_in_stage: null }), null);
});

test("zero is a real age, not a missing one", () => {
  assert.deepEqual(stageAge({ stage: "Stage 1", days_in_stage: 0 }), {
    days: 0,
    censored: false,
    basis: "label",
  });
});

test("daysBetween counts whole calendar days", () => {
  assert.equal(daysBetween("2026-07-30", "2026-09-18"), 50);
  assert.equal(daysBetween("2026-09-18", "2026-09-18"), 0);
});
