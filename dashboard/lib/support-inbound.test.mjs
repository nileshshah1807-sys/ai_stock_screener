import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import test from "node:test";

import { handleInbound, verifySignature } from "./support-inbound.mjs";

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
  const claimed = new Set();
  return {
    calls,
    fetchImpl,
    claim: async (id) => !claimed.has(id) && !!claimed.add(id),
    release: async (id) => void claimed.delete(id),
  };
}

const run = (body, headers, w, extra = {}) =>
  handleInbound({ rawBody: body, headers, env, supportAddress: "support@cupel.in", claim: w.claim, release: w.release, fetchImpl: w.fetchImpl, now: NOW, log: quiet, ...extra });

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
  const result = await handleInbound({ rawBody: body, headers: signed(body), env: { ...env, RESEND_INBOUND_WEBHOOK_SECRET: "" }, supportAddress: "support@cupel.in", claim: w.claim, release: w.release, fetchImpl: w.fetchImpl, now: NOW });
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
  const w = world({ mail: { html: `<p>${"x".repeat(9000)}</p>`, subject: "S" } });
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

test("a message that fails DMARC makes no ticket and is not retried", async () => {
  const w = world({ mail: { ...received, authentication: { dmarc: "fail" } } });
  const body = event();
  const result = await run(body, signed(body), w);
  assert.deepEqual(result, { status: 200, body: { ignored: true } });
  assert.equal(w.calls.filter((c) => c.url.includes("/servicedeskapi/")).length, 0);
});
