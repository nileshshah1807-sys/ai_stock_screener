import assert from "node:assert/strict";
import test from "node:test";

import { viewIsActive } from "./view-match.mjs";

const FRESH_STAGE_2 =
  "minScore=70&stage=Stage+2&minRs=70&sort=advance_age_days&dir=asc";
const ACTIONABLE_BUY =
  "rating=STRONG+BUY&rating=BUY&buyEligible=1&actionable=1&sort=final_score&dir=desc";

const url = (query) => new URLSearchParams(query);

test("a view is active when the URL is exactly it", () => {
  assert.equal(viewIsActive(url(FRESH_STAGE_2), FRESH_STAGE_2), true);
});

test("narrowing a view keeps it active", () => {
  // The reported bug: picking the view and then the STRONG BUY pill left only
  // the pill lit, while the view's filters were plainly still applied.
  assert.equal(
    viewIsActive(url(`${FRESH_STAGE_2}&rating=STRONG+BUY`), FRESH_STAGE_2),
    true,
  );
  assert.equal(
    viewIsActive(url(`${FRESH_STAGE_2}&sector=Financials`), FRESH_STAGE_2),
    true,
  );
});

test("removing or changing one of the view's own filters deactivates it", () => {
  assert.equal(
    viewIsActive(url("minScore=70&stage=Stage+2&sort=advance_age_days&dir=asc"), FRESH_STAGE_2),
    false,
    "minRs dropped",
  );
  assert.equal(
    viewIsActive(url(FRESH_STAGE_2.replace("minScore=70", "minScore=60")), FRESH_STAGE_2),
    false,
    "minScore changed",
  );
  assert.equal(
    viewIsActive(url(FRESH_STAGE_2.replace("dir=asc", "dir=desc")), FRESH_STAGE_2),
    false,
    "sort direction flipped",
  );
});

test("order of repeated keys does not matter", () => {
  const reversed =
    "rating=BUY&rating=STRONG+BUY&buyEligible=1&actionable=1&sort=final_score&dir=desc";
  assert.equal(viewIsActive(url(reversed), ACTIONABLE_BUY), true);
});

test("a view wanting two ratings is not satisfied by one", () => {
  assert.equal(
    viewIsActive(
      url("rating=BUY&buyEligible=1&actionable=1&sort=final_score&dir=desc"),
      ACTIONABLE_BUY,
    ),
    false,
  );
});

test("page number is ignored", () => {
  assert.equal(viewIsActive(url(`${FRESH_STAGE_2}&page=7`), FRESH_STAGE_2), true);
});

test("an empty view is never active", () => {
  assert.equal(viewIsActive(url(FRESH_STAGE_2), ""), false);
  assert.equal(viewIsActive(url(""), ""), false);
});
