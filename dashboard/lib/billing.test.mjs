import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  hasAccess,
  isNewEvent,
  newSubscriptionBody,
  subscriptionChange,
  verifySignature,
  viewerFromClaims,
} from "./billing.mjs";

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
  assert.equal(subscriptionChange(event("authenticated"), "ev1"), null);
  assert.equal(subscriptionChange({ event: "payment.captured", payload: {} }, "ev1"), null);
  const change = subscriptionChange(event("active"), "ev1");
  assert.deepEqual(
    [change.razorpaySubscriptionId, change.userId, change.planId, change.currentPeriodEnd, change.eventId],
    ["sub_1", "u1", "pro", new Date((NOW + 86400) * 1000).toISOString(), "ev1"],
  );
  assert.equal(subscriptionChange(event("cancelled", { current_end: null }), "ev2").currentPeriodEnd, null);
});

test("an event already applied, or older than the stored one, is ignored", () => {
  const change = subscriptionChange(event("active"), "ev2");
  assert.equal(isNewEvent({}, change), true, "first event");
  assert.equal(isNewEvent({ last_event_id: "ev2", last_event_at: change.eventAt }, change), false, "same event again");
  assert.equal(isNewEvent({ last_event_id: "ev1", last_event_at: new Date((NOW + 10) * 1000).toISOString() }, change), false, "older");
  assert.equal(isNewEvent({ last_event_id: "ev1", last_event_at: new Date((NOW - 10) * 1000).toISOString() }, change), true, "newer");
  assert.equal(isNewEvent({}, { ...change, eventId: "" }), false, "no event id, no write");
});

test("new subscription: the first charge waits for the trial, else it is now", () => {
  const plan = { id: "pro", razorpay_plan_id: "plan_X", period: "yearly" };
  const waiting = newSubscriptionBody({ plan, userId: "u1", trialEndsAt: new Date((NOW + 3 * 86400) * 1000).toISOString() }, NOW);
  assert.equal(waiting.start_at, NOW + 3 * 86400);
  assert.deepEqual([waiting.plan_id, waiting.total_count, waiting.notes], ["plan_X", 10, { user_id: "u1", plan_id: "pro" }]);
  const soon = newSubscriptionBody({ plan, userId: "u1", trialEndsAt: new Date((NOW + 600) * 1000).toISOString() }, NOW);
  assert.equal("start_at" in soon, false);
  assert.equal("start_at" in newSubscriptionBody({ plan, userId: "u1", trialEndsAt: null }, NOW), false);
  assert.equal(newSubscriptionBody({ plan: { ...plan, period: "monthly" }, userId: "u1" }, NOW).total_count, 120);
});
