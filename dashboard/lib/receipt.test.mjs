import assert from "node:assert/strict";
import { test } from "node:test";

import { escapeHtml, receiptHtml } from "./receipt.mjs";

const seller = { service: "Cupel", operator: "Op Name", contactEmail: "help@example.com" };
const format = { date: () => "16 Nov 2026", amount: () => "₹129" };
const row = { id: "inv_1", date: "2026-11-16T10:00:00Z", paise: 12900, currency: "INR", method: "UPI", status: "paid", buyerName: "Asha Rao", buyerEmail: "asha@example.com", item: "Monthly" };

test("names the buyer, plan, amount, method and invoice", () => {
  const html = receiptHtml(row, seller, format);
  for (const text of ["Asha Rao<br>asha@example.com", "Monthly", "₹129", "UPI", "inv_1", "16 Nov 2026", "Op Name", "help@example.com"]) assert.ok(html.includes(text), text);
});

test("buyer-supplied text is escaped, never markup", () => {
  const html = receiptHtml({ ...row, buyerName: '<img src=x onerror="alert(1)">' }, seller, format);
  assert.ok(!html.includes("<img"));
  assert.ok(html.includes("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"));
  assert.equal(escapeHtml(`a&'"`), "a&amp;&#39;&quot;");
});

test("a missing buyer says so, and a refund says it was refunded", () => {
  const html = receiptHtml({ ...row, buyerName: null, buyerEmail: null, status: "refunded" }, seller, format);
  assert.ok(html.includes("Not recorded"));
  assert.ok(html.includes("refunded"));
});
