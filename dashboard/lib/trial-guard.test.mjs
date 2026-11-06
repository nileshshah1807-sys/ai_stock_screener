import assert from "node:assert/strict";
import test from "node:test";

import { IP_TRIAL_LIMIT, ipKey, isDisposableEmail, isFreshSignup, mayRevokeTrial, normalizeEmail, trialVerdict } from "./trial-guard.mjs";

const now = { ipHash: "ip1", deviceHash: "dev1", emailHash: "em1", disposable: false };
const prior = (over = {}) => ({ ip_hash: "other", device_hash: "other", email_hash: "other", ...over });

test("normalizeEmail folds gmail dots, plus tags, case and googlemail", () => {
  assert.equal(normalizeEmail("Chi.Ra.yu+trial2@GoogleMail.com"), "chirayu@gmail.com");
  assert.equal(normalizeEmail("a.b+x@fastmail.com"), "a.b@fastmail.com");
  assert.equal(normalizeEmail(" X@Y.in "), "x@y.in");
});

test("isDisposableEmail", () => {
  assert.equal(isDisposableEmail("a+b@Mailinator.com"), true);
  assert.equal(isDisposableEmail("a@gmail.com"), false);
});

test("ipKey keeps IPv4, cuts IPv6 to its /64, takes the first forwarded entry", () => {
  assert.equal(ipKey("49.36.1.2, 10.0.0.1"), "49.36.1.2");
  assert.equal(ipKey("2401:4900:1c:abcd:1:2:3:4"), "2401:4900:001c:abcd");
  assert.equal(ipKey("2401:4900::1"), "2401:4900:0000:0000");
  assert.equal(ipKey("::ffff:1.2.3.4"), "1.2.3.4");
  assert.equal(ipKey(""), null);
  assert.equal(ipKey(undefined), null);
});

test("a clean signup is granted", () => {
  assert.deepEqual(trialVerdict(now, [prior()]), { grant: true, reason: "ok" });
  assert.deepEqual(trialVerdict(now, []), { grant: true, reason: "ok" });
});

test("same email or same device refuses at once", () => {
  assert.equal(trialVerdict(now, [prior({ email_hash: "em1" })]).reason, "same_email");
  assert.equal(trialVerdict(now, [prior({ device_hash: "dev1" })]).reason, "same_device");
});

test("no device signal never matches a prior with none", () => {
  assert.equal(trialVerdict({ ...now, deviceHash: null }, [prior({ device_hash: null })]).grant, true);
});

test("one IP may have IP_TRIAL_LIMIT trials, the next is refused", () => {
  const same = () => prior({ ip_hash: "ip1" });
  const some = Array.from({ length: IP_TRIAL_LIMIT - 1 }, same);
  assert.equal(trialVerdict(now, some).grant, true);
  assert.equal(trialVerdict(now, [...some, same()]).reason, "same_network");
});

test("a missing IP is not a network match", () => {
  assert.equal(trialVerdict({ ...now, ipHash: null }, Array.from({ length: 5 }, () => prior({ ip_hash: null }))).grant, true);
});

test("a disposable domain is refused", () => {
  assert.equal(trialVerdict({ ...now, disposable: true }, []).reason, "disposable_email");
});

test("a user never matches their own signals", () => {
  const own = prior({ user_id: "u1", email_hash: "em1", device_hash: "dev1", ip_hash: "ip1" });
  assert.equal(trialVerdict({ ...now, userId: "u1" }, [own]).grant, true);
  assert.equal(trialVerdict({ ...now, userId: "u2" }, [own]).grant, false);
});

test("only a recent account is a new signup", () => {
  const t = Date.parse("2026-11-06T12:00:00Z");
  assert.equal(isFreshSignup("2026-11-06T11:50:00Z", t), true);
  assert.equal(isFreshSignup("2026-10-01T00:00:00Z", t), false);
  assert.equal(isFreshSignup(null, t), false);
});

test("mayRevokeTrial touches only an unpaid, plan-less trial of an ordinary account", () => {
  const trial = { status: "trialing", plan_id: null, razorpay_subscription_id: null };
  assert.equal(mayRevokeTrial(trial, "trial"), true);
  assert.equal(mayRevokeTrial({ ...trial, plan_id: "monthly" }, "trial"), false);
  assert.equal(mayRevokeTrial({ ...trial, razorpay_subscription_id: "sub_1" }, "trial"), false);
  for (const status of ["active", "past_due", "cancelled", "expired"]) {
    assert.equal(mayRevokeTrial({ ...trial, status }, "monthly"), false);
  }
  assert.equal(mayRevokeTrial(trial, "admin"), false);
  assert.equal(mayRevokeTrial(trial, "allowlist"), false);
  assert.equal(mayRevokeTrial(null, "trial"), false);
});
