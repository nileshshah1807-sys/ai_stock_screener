import assert from "node:assert/strict";
import test from "node:test";

import { objectKey, serveObject } from "./object-gate.mjs";
import { loginPath, shellAccess } from "./shell-access.mjs";

const NOW = 1_800_000_000;
const claims = (extra = {}) => ({
  sub: "u1",
  email: " a@b.in ",
  amr: [{ method: "otp", timestamp: NOW - 3600 }],
  ...extra,
});

test("no session, or one with no email, goes to login keeping the destination", () => {
  assert.deepEqual(shellAccess(null, "/ind/flows", NOW), { kind: "redirect", to: "/login?next=%2Find%2Fflows" });
  assert.equal(shellAccess(claims({ email: "" }), "/ind/flows", NOW).kind, "redirect");
});

test("an over-age session is signed out and sent to login as expired", () => {
  const old = claims({ plan: "admin", amr: [{ method: "otp", timestamp: NOW - 30 * 86_400 }] });
  assert.deepEqual(shellAccess(old, "/ind/flows", NOW), {
    kind: "redirect",
    to: "/login?next=%2Find%2Fflows&error=session_expired",
    signOut: true,
  });
});

test("a lapsed plan goes to pricing; a token with no plan claim asks for a refresh", () => {
  assert.deepEqual(shellAccess(claims({ plan: "trial", access_until: NOW - 1 }), "/x", NOW), {
    kind: "redirect",
    to: "/pricing?lapsed=1",
  });
  assert.deepEqual(shellAccess(claims(), "/x", NOW), { kind: "legacy" });
});

test("an entitled viewer gets an id, a trimmed email and a role", () => {
  const admin = shellAccess(claims({ plan: "admin" }), "/x", NOW);
  assert.equal(admin.kind, "viewer");
  assert.equal(admin.viewer.email, "a@b.in");
  assert.equal(admin.viewer.role, "admin");
  const trial = shellAccess(claims({ plan: "trial", access_until: NOW + 86_400 }), "/x", NOW);
  assert.equal(trial.viewer.role, "viewer");
  assert.equal(trial.viewer.access.daysLeft, 1);
});

test("loginPath matches the proxy's query", () => {
  assert.equal(loginPath("/ind/flows?x=1"), "/login?next=%2Find%2Fflows%3Fx%3D1");
});

test("only the listed objects have keys", () => {
  assert.equal(objectKey("NSE", "fpi-flows"), "live/NSE/fpi-flows.json");
  assert.equal(objectKey("NSE", "sector-directory"), "sectors/NSE/directory.json");
  assert.equal(objectKey("NSE", "quotes"), null);
  assert.equal(objectKey("NSE", "constructor"), null);
  assert.equal(objectKey("LSE", "fpi-flows"), null);
  assert.equal(objectKey(null, null), null);
});

const bucket = { get: async (key) => (key === "live/NSE/fpi-flows.json" ? { body: '{"rows":[]}' } : null) };
const verify = async (token) => (token === "good" ? claims({ plan: "allowlist" }) : null);
const request = (query, token) =>
  new Request(`https://x.test/api/objects?${query}`, token ? { headers: { authorization: `Bearer ${token}` } } : {});

test("an object is passed through only to a verified viewer with access", async () => {
  const ok = await serveObject(request("market=NSE&name=fpi-flows", "good"), bucket, verify);
  assert.equal(ok.status, 200);
  assert.equal(await ok.text(), '{"rows":[]}');
  assert.match(ok.headers.get("cache-control"), /^private/);

  assert.equal((await serveObject(request("market=NSE&name=fpi-flows"), bucket, verify)).status, 401);
  assert.equal((await serveObject(request("market=NSE&name=fpi-flows", "forged"), bucket, verify)).status, 401);
  const throws = async () => { throw new Error("jwks down"); };
  assert.equal((await serveObject(request("market=NSE&name=fpi-flows", "good"), bucket, throws)).status, 401);
  const lapsed = async () => claims({ plan: "trial", access_until: 1 });
  assert.equal((await serveObject(request("market=NSE&name=fpi-flows", "good"), bucket, lapsed)).status, 401);
});

test("an unlisted name is refused before the token is read; a missing object is a 404", async () => {
  let asked = false;
  const spy = async () => ((asked = true), null);
  assert.equal((await serveObject(request("market=NSE&name=quotes", "good"), bucket, spy)).status, 400);
  assert.equal(asked, false);
  assert.equal((await serveObject(request("market=NSE&name=fii-dii-flows", "good"), bucket, verify)).status, 404);
});
