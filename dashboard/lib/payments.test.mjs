import assert from "node:assert/strict";
import { test } from "node:test";

import { cleanDisplayName, initialsOf, shownName } from "./display-name.mjs";
import { methodLabel, paymentRows, receiptUrl } from "./payments.mjs";

const inv = (over) => ({ id: "inv_1", status: "paid", amount: 69900, amount_paid: 69900, currency: "INR", issued_at: 1_762_000_000, paid_at: 1_762_000_100, payment_id: "pay_1", short_url: "https://rzp.io/i/abc", ...over });

test("a paid invoice becomes a row with the paid time, method and receipt", () => {
  const [row] = paymentRows([inv()], { pay_1: { method: "card", card: { network: "Visa", last4: "4242" }, status: "captured" } });
  assert.deepEqual(row, { id: "inv_1", date: new Date(1_762_000_100_000).toISOString(), paise: 69900, currency: "INR", method: "Visa ending 4242", status: "paid", receiptUrl: "https://rzp.io/i/abc" });
});

test("rows are newest first, drafts are dropped, and only chosen fields leave", () => {
  const rows = paymentRows([inv({ id: "a", paid_at: 1_700_000_000 }), inv({ id: "b", paid_at: 1_800_000_000, customer_details: { email: "x@y.z" } }), inv({ id: "c", status: "draft" })]);
  assert.deepEqual(rows.map((r) => r.id), ["b", "a"]);
  assert.deepEqual(Object.keys(rows[0]).sort(), ["currency", "date", "id", "method", "paise", "receiptUrl", "status"]);
});

test("status: refunded and failed and pending read from the payment and the invoice", () => {
  const status = (invoice, payment) => paymentRows([invoice], payment ? { pay_1: payment } : {})[0].status;
  assert.equal(status(inv(), { status: "refunded" }), "refunded");
  assert.equal(status(inv(), { amount_refunded: 100 }), "refunded");
  assert.equal(status(inv({ status: "expired", paid_at: null })), "failed");
  assert.equal(status(inv({ status: "issued", paid_at: null }), { status: "failed" }), "failed");
  assert.equal(status(inv({ status: "issued", paid_at: null })), "pending");
});

test("a payment that could not be read shows its method as not recorded, and the row stays", () => {
  assert.equal(paymentRows([inv()], {})[0].method, "Not recorded");
});

test("methods never carry a full card or UPI id", () => {
  assert.equal(methodLabel({ method: "upi", vpa: "me@bank" }), "UPI");
  assert.equal(methodLabel({ method: "card", card: { network: "RuPay", last4: "12345" } }), "RuPay");
  assert.equal(methodLabel({ method: "emandate" }), "Bank autopay");
  assert.equal(methodLabel(undefined), "Not recorded");
});

test("a receipt link must be https on Razorpay's own host", () => {
  assert.equal(receiptUrl("https://rzp.io/i/x"), "https://rzp.io/i/x");
  assert.equal(receiptUrl("https://invoices.razorpay.com/x"), "https://invoices.razorpay.com/x");
  assert.equal(receiptUrl("http://rzp.io/i/x"), null);
  assert.equal(receiptUrl("https://evilrazorpay.com/x"), null);
  assert.equal(receiptUrl("javascript:alert(1)"), null);
  assert.equal(receiptUrl(null), null);
});

test("display name: cleaned, cleared when empty, refused when too long", () => {
  assert.deepEqual(cleanDisplayName("  Priya \n\t Shah\u0000 "), { ok: true, name: "Priya Shah" });
  assert.deepEqual(cleanDisplayName("   "), { ok: true, name: null });
  assert.equal(cleanDisplayName("x".repeat(61)).ok, false);
  assert.equal(cleanDisplayName("x".repeat(60)).ok, true);
});

test("shown name and initials fall back to the email", () => {
  assert.equal(shownName(" Priya ", "a@b.c"), "Priya");
  assert.equal(shownName(null, "reader@example.com"), "reader");
  assert.equal(initialsOf("Priya Kumari Shah", "a@b.c"), "PS");
  assert.equal(initialsOf("Asha", "a@b.c"), "AS");
  assert.equal(initialsOf(null, "ravi.kumar@example.com"), "RK");
});
