import assert from "node:assert/strict";
import test from "node:test";

import { compose, resendSend, sendOnce } from "./customer-email.mjs";

const quiet = { warn() {} };

/** A claim table like the database's: the first caller of a key wins. */
function fakeStore() {
  const seen = new Set();
  return { claim: (k) => async () => !seen.has(k) && !!seen.add(k), release: (k) => async () => void seen.delete(k) };
}

test("two writers racing for one event send one email", async () => {
  const store = fakeStore();
  const sent = [];
  const go = () => sendOnce({ apiKey: "k", claim: store.claim("paid"), release: store.release("paid"), send: async () => void sent.push(1), log: quiet });
  const results = await Promise.all([go(), go()]);
  assert.deepEqual(results.sort(), ["duplicate", "sent"]);
  assert.equal(sent.length, 1);
});

test("with no key it skips, claims nothing and does not throw", async () => {
  let claimed = false;
  const result = await sendOnce({ apiKey: undefined, claim: async () => (claimed = true), release() {}, send: async () => assert.fail("sent"), log: quiet });
  assert.equal(result, "skipped");
  assert.equal(claimed, false);
});

test("a failed send gives the claim back so a retry can send, and never throws", async () => {
  const store = fakeStore();
  const first = await sendOnce({ apiKey: "k", claim: store.claim("x"), release: store.release("x"), send: async () => { throw new Error("down"); }, log: quiet });
  assert.equal(first, "failed");
  const retry = await sendOnce({ apiKey: "k", claim: store.claim("x"), release: store.release("x"), send: async () => {}, log: quiet });
  assert.equal(retry, "sent");
});

test("a database error while claiming is a failure, not a crash", async () => {
  const result = await sendOnce({ apiKey: "k", claim: async () => { throw new Error("db"); }, release() {}, send: async () => assert.fail("sent"), log: quiet });
  assert.equal(result, "failed");
});

test("Resend gets the sender, recipient and an idempotency key; a refusal throws", async () => {
  let call;
  const ok = async (url, init) => ((call = { url, init }), { ok: true });
  await resendSend(ok, "re_key", { to: "a@b.c", subject: "S", text: "T" }, "u/paid/sub_1");
  assert.equal(call.url, "https://api.resend.com/emails");
  assert.equal(call.init.headers["Idempotency-Key"], "u/paid/sub_1");
  assert.deepEqual(JSON.parse(call.init.body), { from: "Cupel <team@cupel.in>", to: ["a@b.c"], subject: "S", text: "T" });
  await assert.rejects(resendSend(async () => ({ ok: false, status: 422 }), "k", { to: "a@b.c", subject: "S", text: "T" }, "i"), /422/);
});

test("the four emails say what they should and stay plain", () => {
  assert.match(compose("paid", { period: "yearly" }).text, /yearly plan/);
  assert.match(compose("cancelled", { endsAt: "2026-12-31T18:29:59Z" }).text, /until 31 December 2026/);
  assert.match(compose("cancelled", {}).text, /access ends now/);
  const trial = compose("trial_ending", { endsAt: "2026-11-09T10:00:00Z" });
  assert.match(trial.text, /9 November 2026/);
  assert.match(trial.text, /https:\/\/cupel\.in\/account/);
  assert.match(compose("refund", { amountPaise: 99900 }).text, /₹999/);
  for (const kind of ["paid", "cancelled", "trial_ending", "refund"]) assert.doesNotMatch(compose(kind, { endsAt: "2026-12-31T00:00:00Z" }).text, /\b(buy|sell|rating)\b/i);
  assert.throws(() => compose("nope"));
});
