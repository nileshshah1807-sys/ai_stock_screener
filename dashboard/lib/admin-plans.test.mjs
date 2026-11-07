import assert from "node:assert/strict";
import test from "node:test";

import {
  razorpayMode,
  razorpayPlanBody,
  revenueByPlan,
  rupeesToPaise,
  swapPlan,
  validateOffer,
  validatePriceChange,
  validateTrialDays,
} from "./admin-plans.mjs";

const yearly = { id: "pro", name: "Cupel", period: "yearly", amount_paise: 99900 };
const NOW = Date.parse("2026-11-06T00:00:00Z");

test("rupees as typed become paise, or null", () => {
  assert.equal(rupeesToPaise("1,199"), 119900);
  assert.equal(rupeesToPaise("₹999.50"), 99950);
  assert.equal(rupeesToPaise("12.345"), null);
  assert.equal(rupeesToPaise("-5"), null);
  assert.equal(rupeesToPaise(""), null);
});

test("price change: bounds, and it must differ", () => {
  assert.deepEqual(validatePriceChange(yearly, "1199"), { ok: true, oldPaise: 99900, newPaise: 119900 });
  assert.equal(validatePriceChange(yearly, "999").ok, false, "same price");
  assert.equal(validatePriceChange(yearly, "0.5").ok, false, "under Rs 1");
  assert.equal(validatePriceChange(yearly, "9999999").ok, false, "over the cap");
  assert.equal(validatePriceChange(yearly, "abc").ok, false);
});

test("razorpay plan body: a new plan with the period, amount in paise, INR", () => {
  const body = razorpayPlanBody(yearly, 119900);
  assert.deepEqual(body, { period: "yearly", interval: 1, item: { name: "Cupel yearly", amount: 119900, currency: "INR" }, notes: { plan_id: "pro" } });
  assert.equal(razorpayPlanBody({ ...yearly, period: "monthly" }, 12900).period, "monthly");
});

test("offer: all fields blank clears it", () => {
  const r = validateOffer(yearly, { name: "", rupees: "", offerId: "" }, NOW);
  assert.equal(r.ok, true);
  assert.equal(r.offer.razorpay_offer_id, null);
  assert.equal(r.offer.offer_amount_paise, null);
});

test("offer: needs a name, a lower price, a well-formed id, a future end", () => {
  const ok = { name: "Early bird", rupees: "699", offerId: "offer_Abcdefgh123456", endsAt: "2026-12-31T23:59:59+05:30", limit: "500" };
  const r = validateOffer(yearly, ok, NOW);
  assert.equal(r.ok, true);
  assert.deepEqual([r.offer.offer_name, r.offer.offer_amount_paise, r.offer.offer_limit, r.offer.razorpay_offer_id], ["Early bird", 69900, 500, "offer_Abcdefgh123456"]);
  assert.equal(validateOffer(yearly, { ...ok, name: " " }, NOW).ok, false);
  assert.equal(validateOffer(yearly, { ...ok, rupees: "999" }, NOW).ok, false, "not lower than the plan");
  assert.equal(validateOffer(yearly, { ...ok, offerId: "offer_short" }, NOW).ok, false);
  assert.equal(validateOffer(yearly, { ...ok, offerId: "plan_Abcdefgh123456" }, NOW).ok, false);
  assert.equal(validateOffer(yearly, { ...ok, endsAt: "2026-11-01" }, NOW).ok, false, "past");
  assert.equal(validateOffer(yearly, { ...ok, endsAt: "nope" }, NOW).ok, false);
  assert.equal(validateOffer(yearly, { ...ok, limit: "0" }, NOW).ok, false);
  assert.equal(validateOffer(yearly, { ...ok, endsAt: "", limit: "" }, NOW).offer.offer_ends_at, null, "open-ended is allowed");
});

test("trial days: whole number, 1 to 60", () => {
  assert.deepEqual(validateTrialDays("7"), { ok: true, days: 7 });
  assert.equal(validateTrialDays("0").ok, false);
  assert.equal(validateTrialDays("61").ok, false);
  assert.equal(validateTrialDays("3.5").ok, false);
  assert.equal(validateTrialDays("").ok, false);
});

test("revenue: active only, a twelfth a month for yearly, the price the subscriber took", () => {
  const plans = [
    { ...yearly, offer_amount_paise: 69900 },
    { id: "pro-monthly", period: "monthly", amount_paise: 12900 },
  ];
  const subs = [
    { plan_id: "pro", status: "active", offer_applied: true, plan_amount_paise: 99900 },
    { plan_id: "pro", status: "active", offer_applied: false, plan_amount_paise: 79900 }, // took an older price
    { plan_id: "pro", status: "trialing", plan_amount_paise: 99900 },
    { plan_id: "pro-monthly", status: "active", offer_applied: null, plan_amount_paise: null },
    { plan_id: "pro-monthly", status: "cancelled" },
  ];
  const [y, m] = revenueByPlan(plans, subs);
  assert.deepEqual([y.subscribers, y.monthlyPaise], [2, Math.round((69900 + 79900) / 12)]);
  assert.deepEqual([m.subscribers, m.monthlyPaise], [1, 12900]);
});

// A minimal stand-in for supabase-js's update().eq().is().select() chain over one row.
function fakeDb(row) {
  return {
    from: () => ({
      update(fields) {
        const filters = [];
        const q = {
          eq: (c, v) => (filters.push([c, v]), q),
          is: (c, v) => (filters.push([c, v]), q),
          select: async () => {
            if (!filters.every(([c, v]) => (row[c] ?? null) === v)) return { data: [], error: null };
            Object.assign(row, fields);
            return { data: [{ id: row.id }], error: null };
          },
        };
        return q;
      },
    }),
  };
}

test("the plan swap is compare-and-set on the old Razorpay plan id: a second click saves nothing", async () => {
  const row = { id: "pro", razorpay_plan_id: "plan_test", razorpay_offer_id: "offer_x", offer_name: "Early bird" };
  const guard = { column: "razorpay_plan_id", value: "plan_test" };
  assert.equal((await swapPlan(fakeDb(row), "pro", guard, { razorpay_plan_id: "plan_live1" })).result, "saved");
  assert.equal(row.razorpay_plan_id, "plan_live1");
  assert.equal(row.razorpay_offer_id, null);
  assert.equal(row.offer_name, null);
  assert.equal((await swapPlan(fakeDb(row), "pro", guard, { razorpay_plan_id: "plan_live2" })).result, "stale");
  assert.equal(row.razorpay_plan_id, "plan_live1");
});

test("a plan with no Razorpay id yet is guarded on null", async () => {
  const row = { id: "pro", razorpay_plan_id: null };
  const guard = { column: "razorpay_plan_id", value: null };
  assert.equal((await swapPlan(fakeDb(row), "pro", guard, { razorpay_plan_id: "plan_a" })).result, "saved");
  assert.equal((await swapPlan(fakeDb(row), "pro", guard, { razorpay_plan_id: "plan_b" })).result, "stale");
});

test("the mode comes from the key id's prefix", () => {
  assert.equal(razorpayMode("rzp_live_abc"), "live");
  assert.equal(razorpayMode("rzp_test_abc"), "test");
  assert.equal(razorpayMode(undefined), "unknown");
});
