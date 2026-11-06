/**
 * The pure rules of /admin/plans: what a price, offer or trial-length edit
 * must satisfy, and the bodies sent to Razorpay. No I/O, so `node --test`
 * covers it. Every function returns {ok:true, ...} or {ok:false, error}.
 */

const MIN_PAISE = 100; // Razorpay's smallest amount: Rs 1
const MAX_PAISE = 100_000_00; // Rs 1,00,000
export const TRIAL_DAYS_MIN = 1;
export const TRIAL_DAYS_MAX = 60;
/** Razorpay offer ids: "offer_" and 14 letters or digits. */
const OFFER_ID = /^offer_[A-Za-z0-9]{14}$/;

/** @param {string} error */
const bad = (error) => /** @type {{ok: false, error: string}} */ ({ ok: false, error });
/** @template T @param {T} rest */
const good = (rest) => ({ ok: /** @type {true} */ (true), ...rest });

/** Rupees as typed ("1,199" or "999.50") to whole paise, or null. */
export function rupeesToPaise(input) {
  const text = String(input ?? "").replace(/[₹,\s]/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(text)) return null;
  return Math.round(Number(text) * 100);
}

/** A new plan price: bounds, and different from today's. */
export function validatePriceChange(plan, rupees) {
  const paise = rupeesToPaise(rupees);
  if (paise === null) return bad("Enter an amount in rupees, like 999 or 1199.50.");
  if (paise < MIN_PAISE || paise > MAX_PAISE) return bad("The price must be between ₹1 and ₹1,00,000.");
  if (paise === plan.amount_paise) return bad("That is already the price.");
  return good({ oldPaise: plan.amount_paise, newPaise: paise });
}

/**
 * Razorpay plans cannot be edited: a price change is a new plan. The item name
 * is the plan's own name with its period, so the dashboard shows which is which.
 */
export function razorpayPlanBody(plan, amountPaise) {
  return {
    period: plan.period === "yearly" ? "yearly" : "monthly",
    interval: 1,
    item: { name: `${plan.name} ${plan.period}`, amount: amountPaise, currency: "INR" },
    notes: { plan_id: plan.id },
  };
}

/**
 * The introductory offer's fields. Razorpay's offers are made in its dashboard
 * (there is no create call we rely on), so the id is pasted and checked here by
 * shape; the server then asks Razorpay whether it exists.
 * `offer` null/empty name means "no offer": all offer columns cleared.
 */
export function validateOffer(plan, input, now = Date.now()) {
  if (!input.name?.trim() && !input.rupees && !input.offerId) {
    return good({ offer: { offer_name: null, offer_amount_paise: null, offer_ends_at: null, offer_limit: null, razorpay_offer_id: null } });
  }
  if (!input.name?.trim()) return bad("Give the offer a name.");
  const paise = rupeesToPaise(input.rupees);
  if (paise === null || paise < MIN_PAISE) return bad("Enter the offer price in rupees.");
  if (paise >= plan.amount_paise) return bad("The offer price must be lower than the plan price.");
  const offerId = String(input.offerId ?? "").trim();
  if (!OFFER_ID.test(offerId)) return bad("Paste the offer id from the Razorpay dashboard (offer_ followed by 14 characters).");
  let endsAt = null;
  if (input.endsAt) {
    const ms = Date.parse(input.endsAt);
    if (Number.isNaN(ms)) return bad("The end date is not a date.");
    if (ms <= now) return bad("The end date must be in the future.");
    endsAt = new Date(ms).toISOString();
  }
  let limit = null;
  if (input.limit !== "" && input.limit != null) {
    limit = Number(input.limit);
    if (!Number.isInteger(limit) || limit < 1) return bad("The limit is a whole number of subscribers, or empty.");
  }
  return good({
    offer: { offer_name: input.name.trim(), offer_amount_paise: paise, offer_ends_at: endsAt, offer_limit: limit, razorpay_offer_id: offerId },
  });
}

/** What Razorpay's answer to a lookup of an offer id means: only a 404 rejects. */
export function offerLookupVerdict(status) {
  if (status === 200) return good({ verified: true });
  if (status === 404) return bad("Razorpay has no offer with that id.");
  return good({ verified: false });
}

/** Trial length for new sign-ups, in whole days. */
export function validateTrialDays(input) {
  const days = Number(input);
  if (input === "" || !Number.isInteger(days)) return bad("Enter a whole number of days.");
  if (days < TRIAL_DAYS_MIN || days > TRIAL_DAYS_MAX) return bad(`Trial length is ${TRIAL_DAYS_MIN} to ${TRIAL_DAYS_MAX} days.`);
  return good({ days });
}

/**
 * Active subscribers and monthly revenue per plan. `subs` are rows
 * {plan_id, status, plan_amount_paise, offer_applied}; only status "active"
 * counts. A yearly price is a twelfth a month. The amount is the one the
 * subscriber took (plan_amount_paise), falling back to the plan's current price;
 * a subscriber on the early-bird is paying the offer price for the first period.
 */
export function revenueByPlan(plans, subs) {
  return plans.map((plan) => {
    const mine = subs.filter((s) => s.plan_id === plan.id && s.status === "active");
    const paise = mine.reduce((sum, s) => {
      const amount = s.offer_applied === true && plan.offer_amount_paise != null ? plan.offer_amount_paise : (s.plan_amount_paise ?? plan.amount_paise);
      return sum + (plan.period === "yearly" ? amount / 12 : amount);
    }, 0);
    return { planId: plan.id, subscribers: mine.length, monthlyPaise: Math.round(paise) };
  });
}
