import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { test } from "node:test";

import { confirmPayment } from "./billing-confirm.mjs";

const SECRET = "key_secret";
const sign = (p, s) => createHmac("sha256", SECRET).update(`${p}|${s}`).digest("hex");
const entity = (over = {}) => ({ id: "sub_1", status: "active", current_start: 1790000000, current_end: 1800000000, notes: { user_id: "u1", plan_id: "pro" }, ...over });

function run({ userId = "u1", proof, stored = "sub_1", ent = entity() } = {}) {
  const calls = { fetched: 0, applied: [] };
  return confirmPayment({
    userId,
    proof: proof === undefined ? { razorpay_payment_id: "pay_1", razorpay_subscription_id: "sub_1", razorpay_signature: sign("pay_1", "sub_1") } : proof,
    keySecret: SECRET,
    now: () => 1_795_000_000_000,
    storedSubscriptionId: async () => stored,
    fetchEntity: async () => ((calls.fetched += 1), ent),
    apply: async (change) => (calls.applied.push(change), true),
  }).then((r) => ({ ...r, calls }));
}

test("a verified payment on the user's own subscription is applied with Razorpay's time", async () => {
  const r = await run();
  assert.deepEqual([r.status, r.body], [200, { ok: true, applied: true }]);
  assert.equal(r.calls.applied.length, 1);
  assert.equal(r.calls.applied[0].status, "active");
  assert.equal(r.calls.applied[0].eventId, "confirm:pay_1");
  assert.equal(r.calls.applied[0].eventAt, new Date(1790000000 * 1000).toISOString());
});

test("without current_start the time is taken before the fetch", async () => {
  const r = await run({ ent: entity({ current_start: null }) });
  assert.equal(r.calls.applied[0].eventAt, new Date(1_795_000_000_000).toISOString());
});

test("a bad signature is 400 and nothing is fetched or written", async () => {
  const r = await run({ proof: { razorpay_payment_id: "pay_1", razorpay_subscription_id: "sub_1", razorpay_signature: "00" } });
  assert.equal(r.status, 400);
  assert.deepEqual([r.calls.fetched, r.calls.applied.length], [0, 0]);
});

test("another user's subscription is 403 even with a valid signature", async () => {
  const r = await run({ stored: "sub_other" });
  assert.equal(r.status, 403);
  assert.deepEqual([r.calls.fetched, r.calls.applied.length], [0, 0]);
});

test("a subscription whose notes name another user is not applied", async () => {
  const r = await run({ ent: entity({ notes: { user_id: "u2", plan_id: "pro" } }) });
  assert.deepEqual([r.status, r.body], [200, { ok: true, applied: false }]);
  assert.equal(r.calls.applied.length, 0);
});

test("signed out is 401; a not-yet-authorised subscription applies nothing", async () => {
  assert.equal((await run({ userId: "" })).status, 401);
  const r = await run({ ent: entity({ status: "created" }) });
  assert.deepEqual([r.body.applied, r.calls.applied.length], [false, 0]);
});
