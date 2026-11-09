import assert from "node:assert/strict";
import test from "node:test";

import { createLimiter, submitSupport, supportConfigured, validateSupport } from "./support.mjs";

const env = { JSM_SITE: "cupel", JSM_EMAIL: "a@b.in", JSM_API_TOKEN: "tok", JSM_SERVICE_DESK_ID: "1", JSM_REQUEST_TYPE_ID: "10" };
const good = { name: " Asha ", subject: "Refund", message: "Please refund my last payment.", category: "Billing & plans" };
const email = "asha@example.com";
const quiet = { error() {} };
const response = (status, json = {}) => ({ ok: status < 300, status, json: async () => json });
const open = () => true;

test("a valid message is cleaned", () => {
  const checked = validateSupport({ ...good, subject: "Re\u0000fund\n" }, email);
  assert.equal(checked.ok, true);
  assert.equal(checked.value.name, "Asha");
  assert.equal(checked.value.subject, "Re fund");
});

test("bad input is named, not sent", () => {
  for (const patch of [{ name: "" }, { category: "x" }, { subject: "a" }, { message: "short" }, { message: "x".repeat(5001) }]) {
    assert.equal(validateSupport({ ...good, ...patch }, email).ok, false, JSON.stringify(patch));
  }
  assert.equal(validateSupport(null, email).ok, false);
});

test("any unset JSM variable means not configured, and nothing is fetched", async () => {
  assert.equal(supportConfigured(env), true);
  assert.equal(supportConfigured({ ...env, JSM_API_TOKEN: " " }), false);
  const result = await submitSupport({ email, body: good, env: {}, ip: "1", limiter: open, fetchImpl: () => assert.fail("fetched") });
  assert.deepEqual(result, { status: 503, body: { error: "not_configured" } });
});

test("a valid message opens a JSM request on behalf of the customer", async () => {
  let call;
  const fetchImpl = async (url, init) => ((call = { url, init }), { ok: true });
  const result = await submitSupport({ email, body: good, env, ip: "1", limiter: open, fetchImpl });
  assert.equal(result.status, 200);
  assert.equal(call.url, "https://cupel.atlassian.net/rest/servicedeskapi/request");
  const sent = JSON.parse(call.init.body);
  assert.equal(sent.raiseOnBehalfOf, "asha@example.com");
  assert.equal(sent.serviceDeskId, "1");
  assert.match(sent.requestFieldValues.description, /Category: Billing & plans/);
  assert.equal(call.init.headers.Authorization, `Basic ${Buffer.from("a@b.in:tok").toString("base64")}`);
});

test("invalid input is 400 before JSM is called", async () => {
  const result = await submitSupport({ email, body: { ...good, subject: "x" }, env, ip: "1", limiter: open, fetchImpl: () => assert.fail("fetched") });
  assert.equal(result.status, 400);
});

test("a JSM failure is 502 and does not throw", async () => {
  const result = await submitSupport({ email, body: good, env, ip: "1", limiter: open, fetchImpl: async () => response(500), log: quiet });
  assert.equal(result.status, 502);
});

test("a filled honeypot is dropped quietly", async () => {
  const result = await submitSupport({ email, body: { ...good, website: "x" }, env, ip: "1", limiter: open, fetchImpl: () => assert.fail("fetched") });
  assert.equal(result.status, 200);
});

test("the limiter stops the sixth message in a window and frees after it", () => {
  const limiter = createLimiter({ max: 5, windowMs: 1000 });
  for (let i = 0; i < 5; i++) assert.equal(limiter("ip", 0), true);
  assert.equal(limiter("ip", 500), false);
  assert.equal(limiter("other", 500), true);
  assert.equal(limiter("ip", 1500), true);
});

test("signed out: nothing is sent, whatever the body names", async () => {
  const result = await submitSupport({ body: { ...good, email: "stranger@example.com" }, email: null, env, ip: "1", limiter: open, fetchImpl: () => assert.fail("fetched") });
  assert.equal(result.status, 401);
});

test("signed in: JSM is told the session email, not the one typed in the body", async () => {
  let sent;
  const fetchImpl = async (_url, init) => ((sent = JSON.parse(init.body)), { ok: true });
  await submitSupport({ body: { ...good, email: "stranger@example.com" }, email, env, ip: "1", limiter: open, fetchImpl });
  assert.equal(sent.raiseOnBehalfOf, email);
  assert.doesNotMatch(sent.requestFieldValues.description, /stranger/);
});

test("a refusal is logged with JSM's own words, never the token or the message", async () => {
  const logged = [];
  const log = { error: (...args) => logged.push(JSON.stringify(args)) };
  const fetchImpl = async () => response(500, { errorMessage: "boom", errors: { requestTypeId: "bad" } });
  const result = await submitSupport({ email, body: good, env, ip: "1", limiter: open, fetchImpl, log });
  assert.equal(result.status, 502);
  assert.deepEqual(result.body, { error: "send_failed" });
  const text = logged.join("\n");
  assert.match(text, /boom/);
  assert.match(text, /requestTypeId/);
  assert.doesNotMatch(text, /tok|refund my last payment|Basic/);
});

test("an email JSM does not know is added as a customer, then the request is tried again", async () => {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push(url.split("/servicedeskapi")[1]);
    return calls.length === 1 ? response(400, { errorMessage: "unknown customer" }) : response(201);
  };
  const result = await submitSupport({ email, body: good, env, ip: "1", limiter: open, fetchImpl, log: quiet });
  assert.equal(result.status, 200);
  assert.deepEqual(calls, ["/request", "/customer", "/request"]);
});

test("a JSM server error is not retried", async () => {
  let n = 0;
  const result = await submitSupport({ email, body: good, env, ip: "1", limiter: open, fetchImpl: async () => (n++, response(503)), log: quiet });
  assert.equal(result.status, 502);
  assert.equal(n, 1);
});
