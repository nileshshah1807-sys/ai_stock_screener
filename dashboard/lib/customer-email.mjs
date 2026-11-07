/**
 * Cupel's own emails to a customer: what each says, and sending one at most
 * once. No I/O of its own (fetch and the database are passed in), so
 * `node --test` covers it. Plain text only; no ratings or buy/sell wording.
 */

import { priceLabel } from "./billing.mjs";

export const FROM = "Cupel <team@cupel.in>";
const SITE = "https://cupel.in";

/** A stored instant as the India calendar day it falls on, e.g. "31 December 2026". */
const day = (iso) => new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric", timeZone: "Asia/Kolkata" });

const SIGN_OFF = "\n\nThe Cupel team\nReply to this email if you need help.";

/**
 * The subject and body of one email. `d` carries what the kind needs:
 * paid {period}, cancelled {endsAt}, trial_ending {endsAt}, refund {amountPaise}.
 */
export function compose(kind, d = {}, now = Date.now()) {
  switch (kind) {
    case "paid":
      return {
        subject: "Thank you for subscribing to Cupel",
        text: `Thank you for subscribing to Cupel${d.period ? ` (${d.period} plan)` : ""}. Your payment went through and your access is on.\n\nManage your plan any time: ${SITE}/account${SIGN_OFF}`,
      };
    case "cancelled":
      return {
        subject: "Your Cupel plan is cancelled",
        text: `Your Cupel plan is cancelled and will not renew. ${d.endsAt && Date.parse(d.endsAt) > now ? `You keep your access until ${day(d.endsAt)}.` : "Your access has ended."}\n\nChanged your mind? You can subscribe again at ${SITE}/pricing${SIGN_OFF}`,
      };
    case "trial_ending":
      return {
        subject: "Your Cupel free trial ends soon",
        text: `Your free trial ends on ${day(d.endsAt)}. To keep your access, pick a plan before then. Subscribing charges you at once and ends the trial.\n\nPick a plan: ${SITE}/account${SIGN_OFF}`,
      };
    case "refund":
      return {
        subject: "Your Cupel refund has been processed",
        text: `We have refunded ${d.amountPaise ? priceLabel(d.amountPaise) : "your payment"} for Cupel, and your access has ended. How long it takes to show in your account depends on your bank.\n\nOur refund policy: ${SITE}/refunds${SIGN_OFF}`,
      };
    default:
      throw new Error(`unknown email kind: ${kind}`);
  }
}

/** One message through Resend's HTTP API. Throws unless Resend accepts it. */
export async function resendSend(fetchFn, apiKey, { to, subject, text }, idempotencyKey) {
  const response = await fetchFn("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ from: FROM, to: [to], subject, text }),
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error(`Resend answered ${response.status}`);
}

/**
 * Sends at most once per `claim`. No key: log and skip, claiming nothing, so
 * the event can still be sent once a key is set. `claim()` is true for the one
 * caller that wins the event (two writers can race for it); a failed send
 * `release()`s it so a retry can try again. Never throws: a billing request
 * must not fail over an email. Returns "skipped" | "duplicate" | "sent" | "failed".
 */
export async function sendOnce({ apiKey, claim, release, send, log = console }) {
  if (!apiKey) {
    log.warn("customer email skipped: RESEND_API_KEY is not set");
    return "skipped";
  }
  try {
    if (!(await claim())) return "duplicate";
  } catch (error) {
    log.warn("customer email not sent, could not record it", error);
    return "failed";
  }
  try {
    await send();
    return "sent";
  } catch (error) {
    log.warn("customer email not sent", error);
    await Promise.resolve(release()).catch(() => {});
    return "failed";
  }
}
