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
  await resendSend(ok, "re_key", { to: "a@b.c", subject: "S", text: "T", html: "<p>T</p>", replyTo: "support@x.in" }, "u/paid/sub_1");
  assert.equal(call.url, "https://api.resend.com/emails");
  assert.equal(call.init.headers["Idempotency-Key"], "u/paid/sub_1");
  assert.deepEqual(JSON.parse(call.init.body), { from: "Cupel <team@cupel.in>", to: ["a@b.c"], subject: "S", text: "T", html: "<p>T</p>", reply_to: "support@x.in" });
  await assert.rejects(resendSend(async () => ({ ok: false, status: 422 }), "k", { to: "a@b.c", subject: "S", text: "T" }, "i"), /422/);
});

test("the four emails say what they should and stay plain", () => {
  assert.match(compose("paid", { period: "yearly" }).text, /yearly plan/);
  const before = Date.parse("2026-11-07T00:00:00Z");
  assert.match(compose("cancelled", { endsAt: "2026-12-31T18:29:59Z" }, before).text, /until 31 December 2026/);
  assert.match(compose("cancelled", { endsAt: "2026-11-01T00:00:00Z" }, before).text, /access has ended/, "a date already past is not promised");
  assert.match(compose("cancelled", {}, before).text, /access has ended/);
  const trial = compose("trial_ending", { endsAt: "2026-11-09T10:00:00Z" });
  assert.match(trial.text, /9 November 2026/);
  assert.match(trial.text, /https:\/\/cupel\.in\/account/);
  assert.match(compose("refund", { amountPaise: 99900 }).text, /₹999/);
  for (const kind of ["paid", "cancelled", "trial_ending", "refund"]) assert.doesNotMatch(compose(kind, { endsAt: "2026-12-31T00:00:00Z" }).text, /\b(buy|sell|rating)\b/i);
  assert.throws(() => compose("nope"));
});

test("every email has an HTML part with the same facts, links and one button", () => {
  const now = Date.parse("2026-11-07T00:00:00Z");
  const cases = {
    paid: [{ period: "yearly" }, ["yearly plan", "renews by autopay", "cancel anytime in your account", "https://cupel.in/account", "Manage plan"]],
    cancelled: [{ endsAt: "2026-12-31T18:29:59Z" }, ["31 December 2026", "https://cupel.in/pricing", "Subscribe again"]],
    trial_ending: [{ endsAt: "2026-11-09T10:00:00Z" }, ["9 November 2026", "https://cupel.in/account", "Pick a plan"]],
    refund: [{ amountPaise: 99900 }, ["₹999", "https://cupel.in/refunds", "Refund policy"]],
  };
  for (const [kind, [d, facts]] of Object.entries(cases)) {
    const { text, html } = compose(kind, d, now);
    for (const f of facts.filter((f) => f.startsWith("http") || /\d/.test(f))) {
      assert.ok(text.includes(f), `${kind} text has ${f}`);
      assert.ok(html.includes(f), `${kind} html has ${f}`);
    }
    assert.ok(html.includes(facts[2]) && html.includes('alt="Cupel"') && html.includes("max-width:560px"), kind);
    for (const page of ["/terms", "/privacy", "/refunds"]) assert.ok(html.includes(`https://cupel.in${page}`), `${kind} footer ${page}`);
    assert.equal(html.match(/display:inline-block/g).length, 1, "one button");
    assert.doesNotMatch(html, /:<\/p>/, "no dangling colon above the button");
    assert.match(text, /: https:\/\/cupel\.in\//, "the plain text keeps its URL line");
    assert.doesNotMatch(html, /<script|<link|@import|<img[^>]*(1|0)px/i, "no scripts, external fonts or pixels");
  }
});

test("HTML escapes what it is given", () => {
  assert.doesNotMatch(compose("paid", { period: "<b>x</b>" }).html, /<b>x/);
});
