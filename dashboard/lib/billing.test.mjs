import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  accessFromClaims,
  daysLeftLabel,
  isSetUp,
  isEntitled,
  checkoutMethods,
  lapseReason,
  perMonthLabel,
  priceLabel,
  savingPercent,
  hasAccess,
  checkoutAction,
  newSubscriptionBody,
  subscriptionChange,
  viewerFromClaims,
} from "./billing.mjs";
import { verifySignature } from "./webhook-signature.mjs";

const NOW = 1_762_000_000;

test("access: admin and invited users never expire; trial and paid need a future access_until", () => {
  assert.equal(hasAccess({ plan: "admin" }, NOW), true);
  assert.equal(hasAccess({ plan: "allowlist" }, NOW), true);
  assert.equal(hasAccess({ plan: "trial", access_until: NOW + 60 }, NOW), true);
  assert.equal(hasAccess({ plan: "pro", access_until: NOW + 60 }, NOW), true);
  assert.equal(hasAccess({ plan: "trial", access_until: NOW }, NOW), false, "expiry is exclusive");
  assert.equal(hasAccess({ plan: "trial", access_until: NOW - 1 }, NOW), false);
  assert.equal(hasAccess({ plan: "pro" }, NOW), false, "no access_until, no access");
  assert.equal(hasAccess({ plan: "none", access_until: NOW + 60 }, NOW), false);
  assert.equal(hasAccess({ plan: "trial", access_until: "9999999999" }, NOW), false, "a string is not a time");
  assert.equal(hasAccess({}, NOW), false);
  assert.equal(hasAccess(null, NOW), false);
});

test("the database rule says the same", () => {
  const sql = readFileSync(new URL("../../storage/billing_schema.sql", import.meta.url), "utf8");
  assert.ok(sql.includes("'plan' in ('admin', 'allowlist') then true"));
  assert.ok(sql.includes("'plan' = 'none' then false"));
  assert.ok(sql.includes("'access_until', '') ~ '^[0-9]+$'"));
  assert.ok(sql.includes("(auth.jwt() ->> 'access_until')::bigint > floor(extract(epoch from now()))::bigint"));
  assert.ok(sql.includes("'plan' is null then exists"), "a token without the claim falls back to the invite list");
});

test("only an admin plan is the admin role; ratings stay admin-only whatever the plan", () => {
  assert.equal(viewerFromClaims({ plan: "admin" }, NOW).role, "admin");
  for (const plan of ["allowlist", "trial", "pro"]) {
    assert.equal(viewerFromClaims({ plan, access_until: NOW + 5 }, NOW).role, "viewer");
  }
  assert.equal(viewerFromClaims({ plan: "none" }, NOW), null);
});

test("webhook signature: the hex HMAC-SHA256 of the raw body", () => {
  const body = JSON.stringify({ event: "subscription.activated" });
  const good = createHmac("sha256", "whsec").update(body).digest("hex");
  assert.equal(verifySignature(body, good, "whsec"), true);
  assert.equal(verifySignature(body + " ", good, "whsec"), false, "body changed");
  assert.equal(verifySignature(body, good, "other"), false, "wrong secret");
  assert.equal(verifySignature(body, good.slice(1), "whsec"), false, "short signature");
  assert.equal(verifySignature(body, "", "whsec"), false);
  assert.equal(verifySignature(body, undefined, "whsec"), false);
  assert.equal(verifySignature(body, good, ""), false, "no secret configured never verifies");
});

const event = (status, extra = {}) => ({
  event: "subscription.activated",
  created_at: NOW,
  payload: { subscription: { entity: { id: "sub_1", status, current_end: NOW + 86400, notes: { user_id: "u1", plan_id: "pro" }, ...extra } } },
});

test("subscription events map to our statuses; stages before payment change nothing", () => {
  const map = { active: "active", pending: "past_due", halted: "past_due", cancelled: "cancelled", completed: "expired", expired: "expired" };
  for (const [razorpay, ours] of Object.entries(map)) {
    assert.equal(subscriptionChange(event(razorpay), "ev1").status, ours, razorpay);
  }
  assert.equal(subscriptionChange(event("created"), "ev1"), null);
  const authenticated = subscriptionChange(event("authenticated"), "ev1");
  assert.equal(authenticated.status, null, "authorising the mandate changes no status");
  assert.equal(authenticated.planId, "pro");
  assert.equal(subscriptionChange({ event: "payment.captured", payload: {} }, "ev1"), null);
  const change = subscriptionChange(event("active"), "ev1");
  assert.deepEqual(
    [change.razorpaySubscriptionId, change.userId, change.planId, change.currentPeriodEnd, change.eventId],
    ["sub_1", "u1", "pro", new Date((NOW + 86400) * 1000).toISOString(), "ev1"],
  );
  assert.equal(subscriptionChange(event("cancelled", { current_end: null }), "ev2").currentPeriodEnd, null);
});

test("checkout never creates a second subscription beside one that is set up", () => {
  const trialing = { status: "trialing", plan_id: null };
  assert.equal(checkoutAction(null, null, "plan_X"), "create");
  assert.equal(checkoutAction(trialing, null, "plan_X"), "create", "nothing started yet");
  assert.equal(checkoutAction({ status: "trialing", plan_id: "pro" }, null, "plan_X"), "refuse", "mandate authorised in the trial");
  assert.equal(checkoutAction({ status: "active", plan_id: "pro" }, null, "plan_X"), "refuse");
  assert.equal(checkoutAction({ status: "past_due", plan_id: "pro" }, null, "plan_X"), "refuse");
  assert.equal(checkoutAction(trialing, { status: "authenticated", plan_id: "plan_X" }, "plan_X"), "refuse", "webhook not yet seen");
  assert.equal(checkoutAction(trialing, { status: "created", plan_id: "plan_X" }, "plan_X"), "reuse");
  assert.equal(checkoutAction(trialing, { status: "created", plan_id: "plan_Y" }, "plan_X"), "create", "other plan chosen");
  assert.equal(checkoutAction({ status: "cancelled", plan_id: "pro" }, { status: "cancelled", plan_id: "plan_X" }, "plan_X"), "create", "may subscribe again");
  assert.equal(checkoutAction({ status: "expired", plan_id: null }, { status: "expired", plan_id: "plan_X" }, "plan_X"), "create");
});

test("new subscription: the first charge waits for the trial, else it is now", () => {
  const plan = { id: "pro", razorpay_plan_id: "plan_X", period: "yearly" };
  const waiting = newSubscriptionBody({ plan, userId: "u1", trialEndsAt: new Date((NOW + 3 * 86400) * 1000).toISOString() }, NOW);
  assert.equal(waiting.start_at, NOW + 3 * 86400);
  assert.deepEqual([waiting.plan_id, waiting.total_count, waiting.notes], ["plan_X", 10, { user_id: "u1", plan_id: "pro" }]);
  const soon = newSubscriptionBody({ plan, userId: "u1", trialEndsAt: new Date((NOW + 600) * 1000).toISOString() }, NOW);
  assert.equal("start_at" in soon, false);
  assert.equal("start_at" in newSubscriptionBody({ plan, userId: "u1", trialEndsAt: null }, NOW), false);
  assert.equal(newSubscriptionBody({ plan, userId: "u1", offerId: "offer_X" }, NOW).offer_id, "offer_X");
  assert.equal("offer_id" in newSubscriptionBody({ plan, userId: "u1" }, NOW), false);
  assert.equal(newSubscriptionBody({ plan: { ...plan, period: "monthly" }, userId: "u1" }, NOW).total_count, 120);
});

// --- page helpers ---
const DAY = 86_400;
const ACCESS_NOW = 1_800_000_000;

test("a token with no plan claim is legacy", () => {
  assert.equal(accessFromClaims({ sub: "u" }, ACCESS_NOW).kind, "legacy");
});
test("admin and allowlist never expire", () => {
  assert.equal(accessFromClaims({ plan: "admin" }, ACCESS_NOW).kind, "admin");
  assert.equal(accessFromClaims({ plan: "allowlist", access_until: 5 }, ACCESS_NOW).kind, "allowlist");
  assert.ok(isEntitled(accessFromClaims({ plan: "allowlist" }, ACCESS_NOW)));
});
test("a trial counts whole days, rounded up", () => {
  const a = accessFromClaims({ plan: "trial", access_until: ACCESS_NOW + 2 * 3600 }, ACCESS_NOW);
  assert.equal(a.kind, "trial");
  assert.equal(a.daysLeft, 1);
  assert.equal(accessFromClaims({ plan: "trial", access_until: ACCESS_NOW + 7 * DAY }, ACCESS_NOW).daysLeft, 7);
});
test("a paid plan id with time left is paid", () => {
  assert.equal(accessFromClaims({ plan: "monthly_499", access_until: ACCESS_NOW + DAY }, ACCESS_NOW).kind, "paid");
});
test("none, a passed date and a missing date all lapse", () => {
  assert.equal(accessFromClaims({ plan: "none" }, ACCESS_NOW).kind, "lapsed");
  assert.equal(accessFromClaims({ plan: "trial", access_until: ACCESS_NOW - 1 }, ACCESS_NOW).kind, "lapsed");
  assert.equal(accessFromClaims({ plan: "trial" }, ACCESS_NOW).kind, "lapsed");
  assert.ok(!isEntitled(accessFromClaims({ plan: "trial", access_until: NOW }, ACCESS_NOW)));
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

test("the early-bird offer is UPI-only, so its checkout shows UPI alone", () => {
  const m = checkoutMethods(true);
  assert.equal(m.upi, true);
  for (const off of ["card", "netbanking", "wallet", "emi", "paylater", "emandate"]) assert.equal(m[off], false, off);
  assert.equal(checkoutMethods(false), undefined, "no offer: every method stays on");
  assert.equal(checkoutMethods(undefined), undefined);
});
