import assert from "node:assert/strict";
import test from "node:test";

import { pickPayment, refundAndEnd, refundGuard } from "./admin-refund.mjs";

const pay = (over) => ({ id: "pay_1", status: "captured", amount: 49900, amount_refunded: 0, created_at: 1000, currency: "INR", ...over });

function harness({ payments = [pay()], refundOk = true, cancel = "cancelled", end = true } = {}) {
  const calls = [];
  const deps = {
    payment: async () => pickPayment(payments),
    refund: async (id, paise) => { calls.push(["refund", id, paise]); return refundOk ? { ok: true, id: "rfnd_1" } : { ok: false, error: "nope" }; },
    holdCancelMail: async () => { calls.push(["hold"]); },
    notifyRefund: async (id, paise) => { calls.push(["mail", id, paise]); },
    cancel: async () => { calls.push(["cancel"]); return cancel; },
    endAccess: async () => { calls.push(["end"]); return end; },
  };
  return { deps, calls };
}

test("picks the newest taken payment and what is left to refund", () => {
  const picked = pickPayment([pay({ id: "old", created_at: 1 }), pay({ id: "new", created_at: 9, amount_refunded: 100, status: "partially_refunded" }), pay({ id: "failed", status: "failed", created_at: 99 })]);
  assert.equal(picked.id, "new");
  assert.equal(picked.refundablePaise, 49800);
  assert.equal(pickPayment([pay({ status: "failed" })]), null);
  assert.equal(pickPayment([pay({ status: "refunded", amount_refunded: 49900 })]).refundablePaise, 0);
});

test("refund, then cancel, then end access, in that order", async () => {
  const { deps, calls } = harness();
  const r = await refundAndEnd(deps, "pay_1");
  assert.equal(r.ok, true);
  assert.deepEqual(calls, [["refund", "pay_1", 49900], ["hold"], ["cancel"], ["end"], ["mail", "rfnd_1", 49900]]);
});

test("a refused refund changes nothing else", async () => {
  const { deps, calls } = harness({ refundOk: false });
  const r = await refundAndEnd(deps, "pay_1");
  assert.equal(r.ok, false);
  assert.deepEqual(calls, [["refund", "pay_1", 49900]]);
  assert.match(r.problems[0], /Nothing was changed/);
});

test("a payment other than the confirmed one is never refunded", async () => {
  const { deps, calls } = harness();
  const r = await refundAndEnd(deps, "pay_other");
  assert.equal(r.ok, false);
  assert.deepEqual(calls, []);
});

test("a second click does not refund twice but still finishes the job", async () => {
  const { deps, calls } = harness({ payments: [pay({ status: "refunded", amount_refunded: 49900 })], cancel: "already" });
  const r = await refundAndEnd(deps, "pay_1");
  assert.equal(r.ok, true);
  assert.deepEqual(calls, [["hold"], ["cancel"], ["end"]]);
});

test("a failed cancel still ends access and says exactly what happened", async () => {
  const { deps, calls } = harness({ cancel: "failed" });
  const r = await refundAndEnd(deps, "pay_1");
  assert.equal(r.ok, false);
  assert.deepEqual(calls.map((c) => c[0]), ["refund", "hold", "cancel", "end", "mail"]);
  assert.match(r.done.join(), /refunded pay_1/);
  assert.match(r.done.join(), /ended access/);
  assert.match(r.problems[0], /could NOT be cancelled/);
});

test("a failed access end is reported after the refund went through", async () => {
  const { deps } = harness({ end: false });
  const r = await refundAndEnd(deps, "pay_1");
  assert.equal(r.ok, false);
  assert.match(r.done.join(), /refunded pay_1/);
  assert.match(r.problems[0], /access was NOT ended/);
});

test("who may be refunded", () => {
  const target = { id: "u2", role: null };
  const sub = { razorpay_subscription_id: "sub_1" };
  assert.deepEqual(refundGuard({ actorId: "u1", target, sub }), { ok: true, subscriptionId: "sub_1" });
  assert.equal(refundGuard({ actorId: "u2", target, sub }).ok, false);
  assert.equal(refundGuard({ actorId: "u1", target: { id: "u3", role: "admin" }, sub }).ok, false);
  assert.equal(refundGuard({ actorId: "u1", target, sub: { razorpay_subscription_id: null } }).ok, false);
  assert.equal(refundGuard({ actorId: "u1", target: null, sub }).ok, false);
});

test("the SQL that ends access also clears the trial end and the hook refuses a refunded subscription", async () => {
  const { readFileSync } = await import("node:fs");
  const sql = readFileSync(new URL("../../storage/billing_schema.sql", import.meta.url), "utf8");
  const fn = sql.slice(sql.indexOf("function billing_refund_end_access"));
  assert.match(fn.slice(0, fn.indexOf("$$;", 100)), /trial_ends_at = null/);
  assert.match(sql, /refunded_subscription_id is not distinct from sub\.razorpay_subscription_id/);
});
