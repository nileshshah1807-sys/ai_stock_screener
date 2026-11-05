import assert from "node:assert/strict";
import test from "node:test";

import { accessFromClaims, daysLeftLabel, hasAccess, isSetUp, lapseReason, perMonthLabel, priceLabel, savingPercent } from "./plan-access.mjs";

const NOW = 1_800_000_000;
const DAY = 86_400;

test("a token with no plan claim is legacy", () => {
  assert.equal(accessFromClaims({ sub: "u" }, NOW).kind, "legacy");
});
test("admin and allowlist never expire", () => {
  assert.equal(accessFromClaims({ plan: "admin" }, NOW).kind, "admin");
  assert.equal(accessFromClaims({ plan: "allowlist", access_until: 5 }, NOW).kind, "allowlist");
  assert.ok(hasAccess(accessFromClaims({ plan: "allowlist" }, NOW)));
});
test("a trial counts whole days, rounded up", () => {
  const a = accessFromClaims({ plan: "trial", access_until: NOW + 2 * 3600 }, NOW);
  assert.equal(a.kind, "trial");
  assert.equal(a.daysLeft, 1);
  assert.equal(accessFromClaims({ plan: "trial", access_until: NOW + 7 * DAY }, NOW).daysLeft, 7);
});
test("a paid plan id with time left is paid", () => {
  assert.equal(accessFromClaims({ plan: "monthly_499", access_until: NOW + DAY }, NOW).kind, "paid");
});
test("none, a passed date and a missing date all lapse", () => {
  assert.equal(accessFromClaims({ plan: "none" }, NOW).kind, "lapsed");
  assert.equal(accessFromClaims({ plan: "trial", access_until: NOW - 1 }, NOW).kind, "lapsed");
  assert.equal(accessFromClaims({ plan: "trial" }, NOW).kind, "lapsed");
  assert.ok(!hasAccess(accessFromClaims({ plan: "trial", access_until: NOW }, NOW)));
});
test("labels", () => {
  assert.equal(daysLeftLabel(1), "1 day left");
  assert.equal(daysLeftLabel(5), "5 days left");
  assert.equal(priceLabel(49900), "₹499");
  assert.equal(priceLabel(49950), "₹499.50");
  assert.equal(priceLabel(12345600), "₹1,23,456");
  assert.equal(priceLabel("x"), "");
});
test("lapse reason and set-up check", () => {
  assert.equal(lapseReason("cancelled"), "cancelled");
  assert.equal(lapseReason("past_due"), "past_due");
  assert.equal(lapseReason("expired"), "trial_ended");
  assert.equal(lapseReason(undefined), "trial_ended");
  assert.ok(isSetUp({ status: "active" }));
  assert.ok(isSetUp({ status: "trialing", plan_id: "p" }));
  assert.ok(!isSetUp({ status: "trialing", plan_id: null }));
  assert.ok(!isSetUp(null));
});

test("yearly against monthly", () => {
  const yearly = { amount_paise: 99900, period: "yearly" };
  const monthly = { amount_paise: 12900, period: "monthly" };
  assert.equal(perMonthLabel(yearly), "\u20B983");
  assert.equal(perMonthLabel(monthly), "\u20B9129");
  assert.equal(savingPercent(yearly, monthly), 35);
  assert.equal(savingPercent(monthly, yearly), null, "not cheaper");
  assert.equal(savingPercent(yearly, null), null);
});
