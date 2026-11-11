/**
 * Razorpay test plan ids for the staging Worker. Preview shares the production
 * database, whose plans rows hold LIVE plan and offer ids, so a Preview checkout
 * (Razorpay TEST keys) would fail on them. RAZORPAY_TEST_PLANS maps a plan id to
 * test ids: {"pro":{"plan":"plan_..","offer":"offer_.."},"pro-monthly":{"plan":"plan_.."}}.
 * Honoured only outside production; in production it is ignored with a warning.
 * Pure: the environment is passed in.
 */

const isProduction = (env) => env.APP_ENV === "production";

/** The parsed override map, or {} (unset, malformed, or production). */
export function testPlanIds(env = process.env, warn = console.warn) {
  const raw = env.RAZORPAY_TEST_PLANS;
  if (!raw) return {};
  if (isProduction(env)) {
    warn("RAZORPAY_TEST_PLANS is set in production and ignored: it is for Preview only.");
    return {};
  }
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    warn("RAZORPAY_TEST_PLANS is not valid JSON and is ignored.");
    return {};
  }
}

/** The plan row with its Razorpay ids replaced by the test ones, when it has an override. Everything else is untouched. */
export function withTestIds(plan, env = process.env, warn = console.warn) {
  const test = testPlanIds(env, warn)[plan?.id];
  if (!test || typeof test !== "object") return plan;
  return {
    ...plan,
    razorpay_plan_id: typeof test.plan === "string" ? test.plan : plan.razorpay_plan_id,
    razorpay_offer_id: typeof test.offer === "string" ? test.offer : null, // never the live offer id
  };
}

/** Why plan-writing admin actions are refused here, or null in production. Preview and local runs share the live database. */
export function plansReadOnlyReason(env = process.env) {
  return isProduction(env)
    ? null
    : "Plans are read-only outside production: this deploy shares the live database, and a change here would overwrite the live Razorpay plan ids. Change plans on cupel.in.";
}

/**
 * Outside production, checkout runs on test keys against the live database, so a
 * real customer who clicked Subscribe there would get a test subscription id
 * written to their row. Only the emails in PREVIEW_CHECKOUT_EMAILS (comma
 * separated, any case) may start one; with the list unset nobody can.
 * Returns why checkout is refused, or null.
 */
export function previewCheckoutBlock(email, env = process.env) {
  if (isProduction(env)) return null;
  const allowed = String(env.PREVIEW_CHECKOUT_EMAILS ?? "").split(",").map((e) => e.trim().toLowerCase()).filter(Boolean);
  return allowed.includes(String(email ?? "").trim().toLowerCase()) ? null : "preview_checkout_not_allowed";
}
