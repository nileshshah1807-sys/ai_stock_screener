import assert from "node:assert/strict";
import test from "node:test";

import { STATUS_LABEL, historyProgress, statusDetail } from "./new-listings.mjs";

const rupees = (value) => (value == null ? "—" : `₹${value / 1e5} L`);

const base = { sessions_required: 60, turnover_floor: 50_00_000 };

test("short history says how many sessions remain", () => {
  const detail = statusDetail({ ...base, status: "insufficient_history", sessions: 12 }, rupees);
  assert.match(detail, /^12 of the 60 sessions/);
  assert.match(detail, /about 48 more trading days/);
});

test("singular day when one session remains", () => {
  assert.match(
    statusDetail({ ...base, status: "insufficient_history", sessions: 59 }, rupees),
    /about 1 more trading day\./,
  );
});

test("liquidity floor names both the stock's turnover and the floor", () => {
  const detail = statusDetail(
    { ...base, status: "below_liquidity_floor", sessions: 90, median_turnover_20d: 12_00_000 },
    rupees,
  );
  assert.match(detail, /₹12 L a day/);
  assert.match(detail, /₹50 L floor/);
});

test("every status has a label and a sentence", () => {
  for (const status of Object.keys(STATUS_LABEL)) {
    assert.ok(statusDetail({ ...base, status, sessions: 1 }, rupees).length > 10);
  }
});

test("history progress is clamped", () => {
  assert.equal(historyProgress({ ...base, sessions: 30 }), 0.5);
  assert.equal(historyProgress({ ...base, sessions: 90 }), 1);
  assert.equal(historyProgress({ ...base, sessions: null }), 0);
});
