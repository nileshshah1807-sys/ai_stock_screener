import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { test } from "node:test";

import { subscriptionChange } from "./billing.mjs";
import { verifyPaymentSignature } from "./webhook-signature.mjs";

const SECRET = "key_secret";
const sign = (payment, subscription, secret = SECRET) =>
  createHmac("sha256", secret).update(`${payment}|${subscription}`).digest("hex");

test("a checkout signature over payment|subscription verifies", () => {
  assert.ok(verifyPaymentSignature("pay_1", "sub_1", sign("pay_1", "sub_1"), SECRET));
});

test("a wrong, missing, swapped or foreign-keyed signature is rejected", () => {
  assert.ok(!verifyPaymentSignature("pay_1", "sub_1", sign("pay_1", "sub_2"), SECRET));
  assert.ok(!verifyPaymentSignature("pay_2", "sub_1", sign("pay_1", "sub_1"), SECRET));
  assert.ok(!verifyPaymentSignature("pay_1", "sub_1", sign("pay_1", "sub_1", "other"), SECRET));
  assert.ok(!verifyPaymentSignature("pay_1", "sub_1", "", SECRET));
  assert.ok(!verifyPaymentSignature("pay_1", "sub_1", undefined, SECRET));
  assert.ok(!verifyPaymentSignature("", "sub_1", sign("", "sub_1"), SECRET));
  assert.ok(!verifyPaymentSignature("pay_1", "sub_1", sign("pay_1", "sub_1"), ""));
});

test("a fetched subscription becomes the same change the webhook would apply", () => {
  const entity = { id: "sub_1", status: "active", current_end: 1800000000, notes: { user_id: "u1", plan_id: "pro" } };
  const change = subscriptionChange({ event: "subscription.active", payload: { subscription: { entity } }, created_at: 1790000000 }, "confirm:pay_1");
  assert.equal(change.status, "active");
  assert.equal(change.userId, "u1");
  assert.equal(change.planId, "pro");
  assert.equal(change.eventId, "confirm:pay_1");
  // Not yet authorised: nothing to write.
  assert.equal(subscriptionChange({ event: "subscription.created", payload: { subscription: { entity: { ...entity, status: "created" } } }, created_at: 1 }, "x"), null);
});
