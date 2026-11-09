import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import test from "node:test";

import { STALE_CLAIM_MS, automatedReason, claimEmail, handleInbound, verifySignature } from "./support-inbound.mjs";

const SECRET = `whsec_${Buffer.from("inbound-test-secret").toString("base64")}`;
const env = {
  RESEND_INBOUND_WEBHOOK_SECRET: SECRET,
  RESEND_API_KEY: "re_key",
  JSM_SITE: "cupel",
  JSM_EMAIL: "a@b.in",
  JSM_API_TOKEN: "tok",
  JSM_SERVICE_DESK_ID: "1",
  JSM_REQUEST_TYPE_ID: "10",
};
const quiet = { error() {} };
const NOW = 1_800_000_000_000;

const event = (data = {}) =>
  JSON.stringify({ type: "email.received", data: { email_id: "em_1", from: "Asha@Example.com", to: ["support@cupel.in"], subject: "Refund", ...data } });

/** Headers as Resend (Svix) signs them. */
function signed(body, { id = "msg_1", at = NOW / 1000, secret = SECRET } = {}) {
  const key = Buffer.from(secret.replace("whsec_", ""), "base64");
  const signature = `v1,${createHmac("sha256", key).update(`${id}.${at}.${body}`).digest("base64")}`;
  return new Headers({ "svix-id": id, "svix-timestamp": String(at), "svix-signature": signature });
}

const received = { text: "Please refund my last payment.", subject: "Refund", authentication: { dmarc: "pass" } };

/** A Resend + JSM that answers like the real ones and records what was asked. */
function world({ mail = received } = {}) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    if (url.startsWith("https://api.resend.com/emails/receiving/")) return { ok: true, status: 200, json: async () => mail };
    return { ok: true, status: 201, json: async () => ({}) };
  };
  const rows = new Map(); // email id -> { at, done }
  const store = {
    insert: async (id, at) => !rows.has(id) && !!rows.set(id, { at, done: false }),
    reclaim: async (id, staleBefore, at) => {
      const row = rows.get(id);
      return !!row && !row.done && row.at < staleBefore && !!rows.set(id, { at, done: false });
    },
  };
  return {
    calls,
    rows,
    store,
    fetchImpl,
    claim: (id, now = NOW) => claimEmail(store, id, now),
    complete: async (id) => void (rows.get(id).done = true),
    release: async (id) => void rows.delete(id),
  };
}

const run = (body, headers, w, extra = {}) =>
  handleInbound({ rawBody: body, headers, env, supportAddress: "support@cupel.in", claim: w.claim, complete: w.complete, release: w.release, fetchImpl: w.fetchImpl, now: NOW, log: quiet, ...extra });

test("the signature must match the body, be fresh and come from the secret", () => {
  const body = event();
  const h = signed(body);
  const args = { secret: SECRET, id: "msg_1", timestamp: String(NOW / 1000), signature: h.get("svix-signature"), body, now: NOW };
  assert.equal(verifySignature(args), true);
  assert.equal(verifySignature({ ...args, body: body + " " }), false);
  assert.equal(verifySignature({ ...args, now: NOW + 6 * 60 * 1000 }), false);
  assert.equal(verifySignature({ ...args, secret: `whsec_${Buffer.from("other").toString("base64")}` }), false);
});

test("unsigned or wrongly signed calls are 401 and touch nothing", async () => {
  const w = world();
  const body = event();
  assert.equal((await run(body, new Headers(), w)).status, 401);
  assert.equal((await run(body, signed(body, { secret: `whsec_${Buffer.from("x").toString("base64")}` }), w)).status, 401);
  assert.equal(w.calls.length, 0);
});

test("without the secret it is not configured, not open", async () => {
  const w = world();
  const body = event();
  const result = await handleInbound({ rawBody: body, headers: signed(body), env: { ...env, RESEND_INBOUND_WEBHOOK_SECRET: "" }, supportAddress: "support@cupel.in", claim: w.claim, complete: w.complete, release: w.release, fetchImpl: w.fetchImpl, now: NOW });
  assert.equal(result.status, 503);
});

test("mail to another address, or from the support address itself, is ignored", async () => {
  const w = world();
  for (const patch of [{ to: ["team@cupel.in"] }, { from: "Support <support@cupel.in>" }]) {
    const body = event(patch);
    assert.deepEqual((await run(body, signed(body), w)).body, { ignored: true });
  }
  const other = JSON.stringify({ type: "email.sent", data: { email_id: "x", to: ["support@cupel.in"], from: "a@b.c" } });
  assert.deepEqual((await run(other, signed(other), w)).body, { ignored: true });
  assert.equal(w.calls.length, 0);
});

test("happy path: the body is fetched and a JSM request is raised for the sender", async () => {
  const w = world();
  const body = event();
  const result = await run(body, signed(body), w);
  assert.equal(result.status, 200);
  assert.equal(w.calls[0].url, "https://api.resend.com/emails/receiving/em_1");
  assert.equal(w.calls[0].init.headers.Authorization, "Bearer re_key");
  const jsm = w.calls[1];
  assert.equal(jsm.url, "https://cupel.atlassian.net/rest/servicedeskapi/request");
  const sent = JSON.parse(jsm.init.body);
  assert.equal(sent.raiseOnBehalfOf, "asha@example.com");
  assert.equal(sent.requestFieldValues.summary, "Refund");
  assert.match(sent.requestFieldValues.description, /Please refund my last payment\./);
});

test("a long message is capped, and an html-only one is read as text", async () => {
  const w = world({ mail: { html: `<p>${"x".repeat(9000)}</p>`, subject: "S", authentication: { dmarc: "pass" } } });
  const body = event();
  await run(body, signed(body), w);
  const description = JSON.parse(w.calls[1].init.body).requestFieldValues.description;
  assert.ok(description.length < 5200);
  assert.doesNotMatch(description, /<p>/);
});

test("a retry of the same email makes one ticket", async () => {
  const w = world();
  const body = event();
  assert.equal((await run(body, signed(body), w)).status, 200);
  const again = await run(body, signed(body, { id: "msg_2" }), w);
  assert.deepEqual(again.body, { duplicate: true });
  assert.equal(w.calls.filter((c) => c.url.includes("/servicedeskapi/request")).length, 1);
});

test("a failed ticket gives the claim back and answers 502 so Resend retries", async () => {
  const w = world();
  const failing = async (url, init) => (url.includes("/servicedeskapi/") ? { ok: false, status: 503, json: async () => ({}) } : w.fetchImpl(url, init));
  const body = event();
  assert.equal((await run(body, signed(body), w, { fetchImpl: failing })).status, 502);
  assert.equal((await run(body, signed(body), w)).status, 200);
});

test("DMARC fails closed: anything but a pass is dropped, with the reason logged and no body", async () => {
  for (const authentication of [{ dmarc: "fail" }, { dmarc: "none" }, {}, null]) {
    const w = world({ mail: { ...received, authentication } });
    const logged = [];
    const body = event();
    const result = await run(body, signed(body), w, { log: { error: (...a) => logged.push(JSON.stringify(a)) } });
    assert.deepEqual(result, { status: 200, body: { ignored: true } }, JSON.stringify(authentication));
    assert.equal(w.calls.filter((c) => c.url.includes("/servicedeskapi/")).length, 0);
    assert.match(logged.join(), /dmarc/);
    assert.doesNotMatch(logged.join(), /refund my last payment/);
    assert.equal(w.rows.get("em_1").done, true, "a drop is final: no retry");
  }
});

test("auto replies and bounces never open a ticket", async () => {
  assert.equal(automatedReason({ "Auto-Submitted": "auto-replied" }), "auto-submitted");
  assert.equal(automatedReason({ "auto-submitted": "no" }), null);
  assert.equal(automatedReason({ Precedence: "bulk" }), "precedence");
  assert.equal(automatedReason({ "X-Auto-Response-Suppress": "All" }), "auto-response header");
  assert.equal(automatedReason({ "return-path": "<>" }), "bounce");
  assert.equal(automatedReason({ "return-path": "a@b.c" }), null);
  const w = world({ mail: { ...received, headers: { "Auto-Submitted": "auto-replied" } } });
  const body = event();
  assert.deepEqual((await run(body, signed(body), w)).body, { ignored: true });
  assert.equal(w.calls.filter((c) => c.url.includes("/servicedeskapi/")).length, 0);
});

test("a call that timed out leaves a claim the retry takes over once it is stale, and a finished one is never retaken", async () => {
  const w = world();
  assert.equal(await w.claim("em_9", NOW), true); // the call that then died
  assert.equal(await w.claim("em_9", NOW + 1000), false); // a quick retry still sees it taken
  assert.equal(await w.claim("em_9", NOW + STALE_CLAIM_MS + 1), true); // a late retry takes over
  await w.complete("em_9");
  assert.equal(await w.claim("em_9", NOW + 10 * STALE_CLAIM_MS), false);
});

test("a claim that cannot be given back does not stop the 502", async () => {
  const w = world();
  const failing = async (url, init) => (url.includes("/servicedeskapi/") ? { ok: false, status: 503, json: async () => ({}) } : w.fetchImpl(url, init));
  const body = event();
  const result = await run(body, signed(body), w, { fetchImpl: failing, release: async () => { throw new Error("db down"); } });
  assert.equal(result.status, 502);
});
