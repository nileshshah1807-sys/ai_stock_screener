import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

import {
  accessFromClaims,
  autopayLine,
  daysLeftLabel,
  currentPlanId,
  isSetUp,
  planSummary,
  planTitle,
  isEntitled,
  checkoutRestriction,
  lapseReason,
  perMonthLabel,
  priceLabel,
  savingPercent,
  hasAccess,
  checkoutAction,
  isUnknownSubscription,
  lookupResult,
  newSubscriptionBody,
  subscriptionChange,
  viewerFromClaims,
  trialStartLine,
  firstChargePaise,
  trialName,
  daysPhrase,
  ownPricePaise,
  startSubscription,
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

test("subscriptions records whether the offer applied, readable by its owner, never written by an event", () => {
  const sql = readFileSync(new URL("../../storage/billing_schema.sql", import.meta.url), "utf8");
  assert.ok(sql.includes("add column if not exists offer_applied boolean;"));
  assert.match(sql, /grant select \([^)]*\boffer_applied\b[^)]*\)\s+on subscriptions to authenticated/);
  const fn = sql.slice(sql.indexOf("function billing_apply_event"), sql.indexOf("billing_apply_event(text, uuid"));
  assert.ok(!fn.includes("offer_applied"));
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
  assert.equal(checkoutAction(trialing, { status: "created", plan_id: "plan_X", start_at: Date.now() / 1000 + 86400 }, "plan_X"), "create", "legacy start at trial end is not reused");
  assert.equal(checkoutAction({ status: "cancelled", plan_id: "pro" }, { status: "cancelled", plan_id: "plan_X" }, "plan_X"), "create", "may subscribe again");
  assert.equal(checkoutAction({ status: "expired", plan_id: null }, { status: "expired", plan_id: "plan_X" }, "plan_X"), "create");
});

test("new subscription: buying ends the trial, so the first charge is now (no start_at)", () => {
  const plan = { id: "pro", razorpay_plan_id: "plan_X", period: "yearly" };
  // A stray trialEndsAt is ignored: the trial never delays the charge.
  const body = newSubscriptionBody({ plan, userId: "u1", trialEndsAt: new Date((NOW + 3 * 86400) * 1000).toISOString() });
  assert.equal("start_at" in body, false);
  assert.deepEqual([body.plan_id, body.total_count, body.notes], ["plan_X", 10, { user_id: "u1", plan_id: "pro" }]);
  assert.equal(newSubscriptionBody({ plan, userId: "u1", offerId: "offer_X" }).offer_id, "offer_X");
  assert.equal("offer_id" in newSubscriptionBody({ plan, userId: "u1" }), false);
  assert.equal(newSubscriptionBody({ plan: { ...plan, period: "monthly" }, userId: "u1" }).total_count, 120);
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
  const r = checkoutRestriction(true);
  assert.equal(r.method.upi, true);
  for (const off of ["card", "netbanking", "wallet", "emi", "paylater", "emandate"]) assert.equal(r.method[off], false, off);
  assert.deepEqual(r.config.display.sequence, ["block.upi"], "only the UPI block is shown");
  assert.equal(r.config.display.preferences.show_default_blocks, false);
  assert.deepEqual(checkoutRestriction(false), {}, "no offer: every method stays on");
  assert.deepEqual(checkoutRestriction(undefined), {});
});

test("trialStartLine: only a trialing subscription with a plan set up gets the line", () => {
  const plan = { name: "Cupel Monthly", amount_paise: 12900, period: "monthly" };
  const row = { status: "trialing", plan_id: "pro-monthly", trial_ends_at: "2026-11-12T10:00:00Z" };
  assert.equal(trialStartLine(row, plan), "Cupel Monthly starts 12 Nov, first charge ₹129");
  const yearly = { name: "Cupel Yearly", amount_paise: 99900, period: "yearly" };
  const early = { ...yearly, offer_amount_paise: 69900 };
  assert.equal(trialStartLine(row, early), "Cupel Yearly starts 12 Nov", "offer_applied null: name no amount");
  assert.equal(trialStartLine({ ...row, offer_applied: true }, early), "Cupel Yearly starts 12 Nov, first charge ₹699");
  assert.equal(trialStartLine({ ...row, offer_applied: false }, early), "Cupel Yearly starts 12 Nov, first charge ₹999");
  assert.equal(trialStartLine({ ...row, offer_applied: true }, yearly), "Cupel Yearly starts 12 Nov", "no stored offer amount");
  assert.equal(trialStartLine({ ...row, plan_id: null }, plan), null, "no plan set up");
  assert.equal(trialStartLine({ ...row, status: "active" }, plan), null, "already paying");
  assert.equal(trialStartLine(row, null), null, "plan unknown");
  assert.equal(trialStartLine({ ...row, trial_ends_at: null }, plan), null, "no date");
});

describe("planSummary", () => {
  const fmt = (d) => `D(${d})`;
  const money = (p) => `R${p / 100}`;
  const monthly = { name: "Cupel Monthly", period: "monthly", amount_paise: 12900 };
  const yearly = { period: "yearly", amount_paise: 99900, offer: { amount_paise: 69900 } };

  test("trial with a plan set up says when it starts and what it charges", () => {
    const s = planSummary({ kind: "trial", subscription: { status: "trialing", plan_id: "m", trial_ends_at: "2026-11-12T10:00:00Z" }, plan: monthly }, fmt, money);
    assert.equal(s.detail, "Free trial, Cupel Monthly starts 12 Nov, first charge ₹129.");
    assert.deepEqual(s.nextCharge, { date: "2026-11-12T10:00:00Z", paise: 12900 });
  });
  test("first charge follows offer_applied: offer price, plan price, or no amount", () => {
    const sub = { status: "trialing", plan_id: "y", trial_ends_at: "2026-11-12T10:00:00Z" };
    const yearly2 = { ...yearly, name: "Cupel", offer_amount_paise: 69900 };
    const amount = (offer_applied) => planSummary({ kind: "trial", subscription: { ...sub, offer_applied }, plan: yearly2 }, fmt, money).nextCharge?.paise;
    assert.equal(amount(true), 69900);
    assert.equal(amount(false), 99900);
    assert.equal(amount(null), undefined);
    const active = planSummary({ kind: "paid", subscription: { status: "active", plan_id: "y", current_period_end: "e" }, plan: yearly }, fmt, money);
    assert.equal(active.nextCharge.paise, 99900, "a renewal never uses the offer");
  });
  test("cancelled with access left, and past due", () => {
    assert.match(planSummary({ kind: "paid", subscription: { status: "cancelled", plan_id: "m", current_period_end: "e" }, plan: monthly }, fmt).detail, /Access until D\(e\)/);
    assert.equal(planSummary({ kind: "lapsed", subscription: { status: "past_due", plan_id: "m" }, plan: monthly }, fmt).status, "Payment failed");
  });
  test("currentPlanId is set only for a plan that is set up", () => {
    assert.equal(currentPlanId({ status: "active", plan_id: "m" }), "m");
    assert.equal(currentPlanId({ status: "trialing", plan_id: null }), null);
    assert.equal(currentPlanId({ status: "cancelled", plan_id: "m" }), null);
    assert.equal(planTitle(yearly), "Yearly plan");
  });
});

test("a refused trial is its own lapse reason and plan card", async () => {
  const { lapseReason, planSummary } = await import("./billing.mjs");
  assert.equal(lapseReason("expired", "2026-11-06T00:00:00Z"), "trial_unavailable");
  assert.equal(lapseReason("expired"), "trial_ended");
  const card = planSummary({ kind: "lapsed", subscription: { status: "expired", trial_denied_at: "x" }, plan: null }, String);
  assert.equal(card.status, "No free trial");
});

test("a price change never rewrites what an existing subscriber pays", () => {
  const plan = { name: "Cupel", period: "yearly", amount_paise: 119900, offer_amount_paise: 69900 };
  const sub = { status: "active", current_period_end: "2027-11-06T00:00:00Z", plan_amount_paise: 99900 };
  assert.equal(planSummary({ kind: "paid", subscription: sub, plan }, (d) => d).nextCharge.paise, 99900);
  assert.equal(planSummary({ kind: "paid", subscription: { ...sub, plan_amount_paise: null }, plan }, (d) => d).nextCharge.paise, 119900, "unrecorded: the plan's price");
  assert.equal(firstChargePaise({ plan_amount_paise: 99900, offer_applied: false }, plan), 99900);
});

test("the trial's length in words", () => {
  assert.equal(trialName(7), "7-day free trial");
  assert.equal(trialName(14), "14-day free trial");
  assert.equal(daysPhrase(1), "1 day");
  assert.equal(daysPhrase(10), "10 days");
});

describe("startSubscription", () => {
  const plan = { id: "yearly", razorpay_plan_id: "plan_1", period: "yearly" };
  const args = { plan, userId: "u1", offerId: "offer_bad" };
  const run = async (replies) => {
    const sent = [];
    const post = async (body) => (sent.push(body), replies.shift());
    return { ...(await startSubscription(post, args)), sent };
  };

  test("a 400 naming the offer retries once without it", async () => {
    const reject = { ok: false, status: 400, json: { error: { description: "The offer id is invalid" } } };
    const r = await run([reject, { ok: true, status: 200, json: { id: "sub_1" } }]);
    assert.equal(r.sent.length, 2);
    assert.equal(r.sent[0].offer_id, "offer_bad");
    assert.equal("offer_id" in r.sent[1], false);
    assert.equal(r.offered, false);
    assert.equal(r.rejection, "The offer id is invalid");
    assert.equal(r.response.json.id, "sub_1");
  });

  test("any other failure is not retried", async () => {
    const other = { ok: false, status: 400, json: { error: { description: "The plan id is invalid" } } };
    const r = await run([other]);
    assert.equal(r.sent.length, 1);
    assert.equal(r.rejection, null);
    assert.equal(r.response.ok, false);
  });
});

test("the account header price is the subscriber's own, not today's", () => {
  const plan = { amount_paise: 13900 };
  assert.equal(ownPricePaise({ plan_amount_paise: 12900 }, plan), 12900, "price raised after they subscribed");
  assert.equal(ownPricePaise({ plan_amount_paise: null }, plan), 13900, "unrecorded: the plan's price");
  assert.equal(ownPricePaise(null, plan), 13900);
});

test("a stored subscription id Razorpay has never heard of (404) does not block checkout", () => {
  assert.deepEqual(lookupResult(false, 404, { error: {} }), { stale: true });
  assert.deepEqual(lookupResult(true, 200, { id: "sub_1", status: "created" }), { existing: { id: "sub_1", status: "created" } });
  for (const [ok, status, json] of [[false, 500, null], [false, 401, {}], [false, 0, null], [true, 200, {}], [true, 200, null]]) {
    assert.deepEqual(lookupResult(ok, status, json), { error: true });
  }
});

test("the unknown-subscription rule: 404, or a 400 that says the id does not exist, and nothing else", () => {
  assert.equal(isUnknownSubscription(404, null), true);
  const real = { error: { code: "BAD_REQUEST_ERROR", description: "The ID provided is invalid or could not be found." } }; // Razorpay's actual reply
  assert.equal(isUnknownSubscription(400, real), true);
  assert.equal(isUnknownSubscription(400, { error: { code: "BAD_REQUEST_ERROR", description: "The id provided does not exist" } }), true);
  assert.equal(isUnknownSubscription(400, { error: { code: "SERVER_ERROR", description: real.error.description } }), false);
  assert.equal(isUnknownSubscription(400, { error: { description: real.error.description } }), false); // no code
  assert.equal(isUnknownSubscription(400, { error: { code: "BAD_REQUEST_ERROR", description: "The amount must be at least 100" } }), false);
  assert.equal(isUnknownSubscription(400, null), false);
  assert.equal(isUnknownSubscription(401, { error: { description: "does not exist" } }), false);
  assert.equal(isUnknownSubscription(500, null), false);
  assert.deepEqual(lookupResult(false, 400, real), { stale: true });
  assert.deepEqual(lookupResult(false, 400, { error: { code: "BAD_REQUEST_ERROR", description: "Bad request" } }), { error: true });
});

describe("autopay wording", () => {
  test("the pricing card's line takes its period and price from the plan", () => {
    assert.match(autopayLine({ period: "monthly", amount_paise: 12900 }), /^Renews every month by autopay .* at ₹129 until you cancel\. Cancel anytime in your account\.$/);
    assert.match(autopayLine({ period: "yearly", amount_paise: 99900 }), /every year .* at ₹999 /);
    // An open early-bird is UPI only at checkout, so no other method is promised.
    assert.equal(autopayLine({ period: "yearly", amount_paise: 99900, offer: { amount_paise: 69900 } }), "Renews every year by UPI AutoPay at ₹999 until you cancel. Cancel anytime in your account.");
  });

  test("an active plan says autopay is on, the date and amount, and that access stays", () => {
    const plan = { id: "m", name: "Cupel", period: "monthly", amount_paise: 12900 };
    const s = planSummary({ kind: "paid", subscription: { status: "active", plan_id: "m", current_period_end: "2026-12-07T00:00:00Z" }, plan }, (d) => `on ${d.slice(0, 10)}`, priceLabel);
    assert.equal(s.detail, "Autopay is on: renews on on 2026-12-07 for ₹129. Cancel anytime, access stays until then.");
  });
});
