import assert from "node:assert/strict";
import test from "node:test";

import { plansReadOnlyReason, testPlanIds, withTestIds } from "./plan-overrides.mjs";

const MAP = JSON.stringify({ pro: { plan: "plan_T", offer: "offer_T" }, "pro-monthly": { plan: "plan_M" } });
const live = { id: "pro", razorpay_plan_id: "plan_LIVE", razorpay_offer_id: "offer_LIVE", amount_paise: 100 };
const quiet = () => {};

test("on Preview the test ids replace the live ones, only for listed plans", () => {
  const env = { VERCEL_ENV: "preview", RAZORPAY_TEST_PLANS: MAP };
  const out = withTestIds(live, env, quiet);
  assert.equal(out.razorpay_plan_id, "plan_T");
  assert.equal(out.razorpay_offer_id, "offer_T");
  assert.equal(out.amount_paise, 100);
  const monthly = withTestIds({ id: "pro-monthly", razorpay_plan_id: "plan_LIVE2", razorpay_offer_id: "offer_LIVE2" }, env, quiet);
  assert.equal(monthly.razorpay_plan_id, "plan_M");
  assert.equal(monthly.razorpay_offer_id, null); // a live offer id is never used with test keys
  const other = { id: "other", razorpay_plan_id: "plan_X", razorpay_offer_id: null };
  assert.equal(withTestIds(other, env, quiet), other);
});

test("the override is ignored in production, with a warning", () => {
  const warnings = [];
  const env = { VERCEL_ENV: "production", RAZORPAY_TEST_PLANS: MAP };
  assert.deepEqual(testPlanIds(env, (m) => warnings.push(m)), {});
  assert.equal(withTestIds(live, env, quiet), live);
  assert.match(warnings[0], /ignored/);
});

test("unset or malformed leaves the row alone", () => {
  assert.equal(withTestIds(live, { VERCEL_ENV: "preview" }, quiet), live);
  assert.equal(withTestIds(live, { VERCEL_ENV: "preview", RAZORPAY_TEST_PLANS: "{nope" }, quiet), live);
  assert.equal(withTestIds(live, { VERCEL_ENV: "preview", RAZORPAY_TEST_PLANS: "[1]" }, quiet), live);
});

test("plan writes are refused everywhere but production", () => {
  assert.equal(plansReadOnlyReason({ VERCEL_ENV: "production" }), null);
  for (const VERCEL_ENV of ["preview", "development", undefined]) assert.match(plansReadOnlyReason({ VERCEL_ENV }), /read-only/);
});

test("every admin plan write checks the read-only guard first", async () => {
  const { readFileSync } = await import("node:fs");
  const src = readFileSync(new URL("./admin-plans-server.ts", import.meta.url), "utf8");
  for (const name of ["changePrice", "relinkPlan", "saveOffer", "setPlanOpen", "setTrialDays"]) {
    const body = src.slice(src.indexOf(`export async function ${name}(`)).split("\nexport ")[0];
    assert.match(body, /readOnly\(\)/, `${name} must refuse outside production`);
    assert.ok(body.indexOf("readOnly()") < body.indexOf(".update(") || !body.includes(".update("), name);
  }
});

test("outside production only listed emails may start a checkout; production is unaffected", async () => {
  const { previewCheckoutBlock } = await import("./plan-overrides.mjs");
  const env = { VERCEL_ENV: "preview", PREVIEW_CHECKOUT_EMAILS: " Test@Example.com ,b@x.co" };
  assert.equal(previewCheckoutBlock("test@example.com", env), null);
  assert.equal(previewCheckoutBlock("real@customer.in", env), "preview_checkout_not_allowed");
  assert.equal(previewCheckoutBlock(undefined, env), "preview_checkout_not_allowed");
  assert.equal(previewCheckoutBlock("test@example.com", { VERCEL_ENV: "preview" }), "preview_checkout_not_allowed"); // list unset: nobody
  assert.equal(previewCheckoutBlock("real@customer.in", { VERCEL_ENV: "production" }), null);
  assert.equal(previewCheckoutBlock("real@customer.in", { VERCEL_ENV: "production", PREVIEW_CHECKOUT_EMAILS: "" }), null);
});
