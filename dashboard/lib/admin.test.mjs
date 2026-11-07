import assert from "node:assert/strict";
import test from "node:test";

import {
  buildRow, cancelSettled, canAdminister, exactLike, complimentaryPlan, deletePlan, filterRows, isEmail, logEntry, nextCharge, parseDays,
  planClaim, razorpayLinkLabel, razorpayUrl, trialPlan, undoDenialPlan,
} from "./admin.mjs";

const NOW = Date.parse("2026-11-06T00:00:00Z");
const DAY = 86_400_000;
const at = (days) => new Date(NOW + days * DAY).toISOString();

test("only a verified admin viewer may administer", () => {
  assert.equal(canAdminister({ id: "u1", role: "admin" }), true);
  assert.equal(canAdminister({ id: "u1", role: "viewer" }), false);
  assert.equal(canAdminister({ role: "admin" }), false);
  assert.equal(canAdminister(null), false);
  assert.equal(canAdminister(undefined), false);
});

test("email and days validation", () => {
  assert.equal(isEmail("a@b.co"), true);
  assert.equal(isEmail("a b@c.com"), false);
  assert.equal(isEmail("nope"), false);
  assert.equal(parseDays("7"), 7);
  for (const bad of ["0", "-1", "1.5", "366", "", "x", null]) assert.equal(parseDays(bad), null);
});

test("plan claim mirrors the token hook", () => {
  assert.equal(planClaim({ role: "admin" }, null, NOW), "admin");
  assert.equal(planClaim({ role: "viewer" }, { status: "expired" }, NOW), "allowlist");
  assert.equal(planClaim(null, null, NOW), "none");
  assert.equal(planClaim(null, { status: "trialing", trial_ends_at: at(2) }, NOW), "trial");
  assert.equal(planClaim(null, { status: "trialing", trial_ends_at: at(-1) }, NOW), "none");
  assert.equal(planClaim(null, { status: "active", plan_id: "yearly", current_period_end: at(30) }, NOW), "yearly");
  assert.equal(planClaim(null, { status: "expired", current_period_end: at(30) }, NOW), "none");
});

test("next charge", () => {
  assert.equal(nextCharge({ status: "active", current_period_end: at(5) }), at(5));
  assert.equal(nextCharge({ status: "trialing", trial_ends_at: at(3) }), null);
  assert.equal(nextCharge({ status: "trialing", trial_ends_at: at(3), razorpay_subscription_id: "sub_1" }), at(3));
  assert.equal(nextCharge({ status: "cancelled", current_period_end: at(5) }), null);
  assert.equal(nextCharge(null), null);
});

const user = (id, email, extra = {}) => ({ id, email, created_at: at(-9), user_metadata: {}, ...extra });
const rows = [
  buildRow(user("1", "Ann@x.com", { user_metadata: { full_name: "Ann Lee" } }), { status: "trialing", trial_ends_at: at(2) }, { granted: true, reason: "ok" }, null, NOW),
  buildRow(user("2", "bob@x.com"), { status: "expired", trial_denied_at: at(-1) }, { granted: false, reason: "same_ip" }, null, NOW),
  buildRow(user("3", "cy@x.com"), { status: "active", plan_id: "yearly", current_period_end: at(20), razorpay_subscription_id: "sub_9" }, null, null, NOW),
  buildRow(user("4", "di@x.com"), null, null, { role: "viewer" }, NOW),
  buildRow(user("5", "ed@x.com"), null, null, { role: "admin" }, NOW),
];

test("rows carry the guard result and lower-cased email", () => {
  assert.equal(rows[0].email, "ann@x.com");
  assert.deepEqual(rows[1].guard, { result: "denied", reason: "same_ip" });
  assert.equal(rows[0].guard.result, "granted");
  assert.equal(rows[2].guard, null);
  assert.equal(rows[2].next_charge, at(20));
});

test("search and filter", () => {
  const ids = (opts) => filterRows(rows, opts).map((r) => r.id);
  assert.deepEqual(ids({ q: "ANN" }), ["1"]);
  assert.deepEqual(ids({ q: "lee" }), ["1"]);
  assert.deepEqual(ids({ status: "trialing" }), ["1"]);
  assert.deepEqual(ids({ status: "denied" }), ["2"]);
  assert.deepEqual(ids({ status: "complimentary" }), ["4"]);
  assert.deepEqual(ids({ status: "admin" }), ["5"]);
  assert.deepEqual(ids({ status: "none" }), ["2"]);
  assert.deepEqual(ids({ status: "active", q: "x.com" }), ["3"]);
  assert.equal(ids({}).length, 5);
});

test("razorpay link", () => {
  assert.equal(razorpayUrl("sub_9"), "https://dashboard.razorpay.com/app/subscriptions/sub_9");
  assert.equal(razorpayUrl("../evil"), null);
  assert.equal(razorpayLinkLabel("rzp_live_x"), "Subscription in Razorpay");
  assert.match(razorpayLinkLabel("rzp_test_x"), /test mode: switch the dashboard to Test/);
  assert.equal(razorpayUrl(null), null);
});

test("trial extend adds to the later of now and the current end; restart sets from now and lifts a denial", () => {
  const sub = { status: "trialing", trial_ends_at: at(3), trial_denied_at: null };
  assert.equal(trialPlan(sub, "extend", 7, NOW).patch.trial_ends_at, at(10));
  assert.equal(trialPlan({ ...sub, trial_ends_at: at(-5) }, "extend", 7, NOW).patch.trial_ends_at, at(7));
  const restart = trialPlan({ status: "expired", trial_ends_at: at(-5), trial_denied_at: at(-4) }, "restart", 7, NOW);
  assert.equal(restart.patch.trial_ends_at, at(7));
  assert.equal(restart.patch.status, "trialing");
  assert.equal(restart.patch.trial_denied_at, null);
  assert.equal(trialPlan(sub, "extend", 0, NOW).ok, false);
  assert.equal(trialPlan(sub, "bogus", 5, NOW).ok, false);
  assert.equal(trialPlan(null, "extend", 5, NOW).ok, false);
  assert.equal(trialPlan({ status: "active" }, "extend", 5, NOW).ok, false);
});

test("complimentary access never touches an admin", () => {
  assert.equal(complimentaryPlan(null, true).op, "insert");
  assert.equal(complimentaryPlan({ role: "viewer" }, false).op, "delete");
  assert.equal(complimentaryPlan({ role: "viewer" }, true).ok, false);
  assert.equal(complimentaryPlan(null, false).ok, false);
  assert.equal(complimentaryPlan({ role: "admin" }, true).ok, false);
  assert.equal(complimentaryPlan({ role: "admin" }, false).ok, false);
});

test("undo denial writes the two statements of trial_guard_schema.sql", () => {
  const plan = undoDenialPlan({ trial_denied_at: at(-1) }, { granted: false }, NOW);
  assert.deepEqual(plan.subscription, { status: "trialing", trial_ends_at: at(7), trial_denied_at: null, updated_at: at(0) });
  assert.deepEqual(plan.signal, { granted: false, reason: "overridden" });
  assert.equal(undoDenialPlan({ trial_denied_at: at(-1) }, { granted: false }, NOW, 14).subscription.trial_ends_at, at(14));
  assert.equal(undoDenialPlan({ trial_denied_at: null }, { granted: true }, NOW).ok, false);
});

test("delete: checks the address, refuses self and admins, cancels a live subscription first", () => {
  const target = { id: "9", email: "z@x.com", role: null };
  const live = { status: "active", razorpay_subscription_id: "sub_1" };
  assert.deepEqual(deletePlan({ actorId: "1", target, sub: live, typedEmail: "Z@x.com" }), { ok: true, cancelFirst: "sub_1" });
  assert.deepEqual(deletePlan({ actorId: "1", target, sub: { status: "cancelled", razorpay_subscription_id: "sub_1" }, typedEmail: "z@x.com" }), { ok: true, cancelFirst: null });
  assert.equal(deletePlan({ actorId: "1", target, sub: null, typedEmail: "z@x.com" }).cancelFirst, null);
  assert.equal(deletePlan({ actorId: "1", target, sub: live, typedEmail: "other@x.com" }).ok, false);
  assert.equal(deletePlan({ actorId: "9", target, sub: live, typedEmail: "z@x.com" }).ok, false);
  assert.equal(deletePlan({ actorId: "1", target: { ...target, role: "admin" }, sub: live, typedEmail: "z@x.com" }).ok, false);
  assert.equal(deletePlan({ actorId: "1", target: null, sub: null, typedEmail: "" }).ok, false);
});

test("log entry names who, what, target and when; unknown actions throw", () => {
  const entry = logEntry({ id: "1", email: "a@x.com" }, "delete", { id: "9", email: "z@x.com" }, { cancelled: "sub_1" }, NOW);
  assert.deepEqual(entry, { admin_id: "1", admin_email: "a@x.com", action: "delete", target_id: "9", target_email: "z@x.com", detail: { cancelled: "sub_1" }, created_at: at(0) });
  assert.throws(() => logEntry({ id: "1", email: "a" }, "Bad Action!", {}));
});

test("an address matches only itself in an ilike: _ % and \\ are escaped", () => {
  assert.equal(exactLike("A_b@x.com"), "a\\_b@x.com");
  assert.equal(exactLike("a%b@x.com"), "a\\%b@x.com");
  assert.equal(exactLike("a\\b@x.com"), "a\\\\b@x.com");
  assert.equal(exactLike(" plain@x.com "), "plain@x.com");
});

test("an unknown subscription lets a delete go on only in production", () => {
  const unknown = { error: { code: "BAD_REQUEST_ERROR", description: "The ID provided is invalid or could not be found." } };
  assert.equal(cancelSettled(true, 200, null, { VERCEL_ENV: "preview" }), true);
  assert.equal(cancelSettled(false, 400, unknown, { VERCEL_ENV: "production" }), true);
  // Preview has test keys on the live database: the same answer is given for a real customer's live subscription.
  assert.equal(cancelSettled(false, 400, unknown, { VERCEL_ENV: "preview" }), false);
  assert.equal(cancelSettled(false, 404, null, {}), false);
  assert.equal(cancelSettled(false, 500, null, { VERCEL_ENV: "production" }), false);
});
