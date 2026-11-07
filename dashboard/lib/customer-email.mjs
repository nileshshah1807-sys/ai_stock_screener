/**
 * Cupel's own emails to a customer: what each says, and sending one at most
 * once. No I/O of its own (fetch and the database are passed in), so
 * `node --test` covers it. Plain text and HTML; no ratings or buy/sell wording.
 */

import { priceLabel } from "./billing.mjs";

export const FROM = "Cupel <team@cupel.in>";
const SITE = "https://cupel.in";

/** A stored instant as the India calendar day it falls on, e.g. "31 December 2026". */
const day = (iso) => new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric", timeZone: "Asia/Kolkata" });

const SIGN_OFF = "The Cupel team\nReply to this email if you need help.";

/**
 * What each email says: a subject, short paragraphs and one button. The plain
 * text and the HTML are both made from this, so they cannot disagree.
 * `d` carries what the kind needs: paid {period}, cancelled {endsAt},
 * trial_ending {endsAt}, refund {amountPaise}.
 */
function content(kind, d, now) {
  switch (kind) {
    case "paid":
      return {
        subject: "Thank you for subscribing to Cupel",
        heading: "Thank you for subscribing",
        paragraphs: [`Thank you for subscribing to Cupel${d.period ? ` (${d.period} plan)` : ""}. Your payment went through and your access is on.`, "Manage your plan any time:"],
        button: { label: "Manage plan", href: `${SITE}/account` },
      };
    case "cancelled":
      return {
        subject: "Your Cupel plan is cancelled",
        heading: "Your plan is cancelled",
        paragraphs: [`Your Cupel plan is cancelled and will not renew. ${d.endsAt && Date.parse(d.endsAt) > now ? `You keep your access until ${day(d.endsAt)}.` : "Your access has ended."}`, "Changed your mind? You can subscribe again at:"],
        button: { label: "Subscribe again", href: `${SITE}/pricing` },
      };
    case "trial_ending":
      return {
        subject: "Your Cupel free trial ends soon",
        heading: "Your free trial ends soon",
        paragraphs: [`Your free trial ends on ${day(d.endsAt)}. To keep your access, pick a plan before then. Subscribing charges you at once and ends the trial.`, "Pick a plan:"],
        button: { label: "Pick a plan", href: `${SITE}/account` },
      };
    case "refund":
      return {
        subject: "Your Cupel refund has been processed",
        heading: "Your refund is processed",
        paragraphs: [`We have refunded ${d.amountPaise ? priceLabel(d.amountPaise) : "your payment"} for Cupel, and your access has ended. How long it takes to show in your account depends on your bank.`, "Our refund policy:"],
        button: { label: "Refund policy", href: `${SITE}/refunds` },
      };
    default:
      throw new Error(`unknown email kind: ${kind}`);
  }
}

const esc = (t) => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
// The app's own light tokens (app/globals.css): ground, card, border, text, muted, primary.
const C = { ground: "#fafafa", card: "#ffffff", border: "#e4e4e7", text: "#09090b", muted: "#5f5f68", primary: "#18181b", onPrimary: "#fafafa" };
const FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";

/** Table layout, inline CSS, 560px wide, light: what mail clients render alike. No images but the logo, no tracking. */
function html({ subject, heading, paragraphs, button }) {
  const link = (href, label) => `<a href="${esc(href)}" style="color:${C.muted};text-decoration:underline;">${esc(label)}</a>`;
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>${esc(subject)}</title></head>
<body style="margin:0;padding:0;background:${C.ground};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:${C.ground};"><tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;font-family:${FONT};color:${C.text};">
<tr><td style="padding:0 4px 16px 4px;"><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
<td style="padding-right:10px;"><img src="${SITE}/email/cupel-mark.png" width="32" height="32" alt="Cupel" style="display:block;border:0;"></td>
<td style="font-size:18px;font-weight:600;color:${C.text};">Cupel</td></tr></table></td></tr>
<tr><td style="background:${C.card};border:1px solid ${C.border};border-radius:12px;padding:28px;">
<h1 style="margin:0 0 16px 0;font-size:22px;line-height:28px;font-weight:600;color:${C.text};">${esc(heading)}</h1>
<p style="margin:0 0 16px 0;font-size:16px;line-height:24px;color:${C.text};">${esc(paragraphs[0])}</p>
<p style="margin:0 0 20px 0;font-size:16px;line-height:24px;color:${C.muted};">${esc(paragraphs[1])}</p>
<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr><td style="background:${C.primary};border-radius:8px;"><a href="${esc(button.href)}" style="display:inline-block;padding:12px 22px;font-size:16px;font-weight:600;color:${C.onPrimary};text-decoration:none;">${esc(button.label)}</a></td></tr></table>
</td></tr>
<tr><td style="padding:16px 4px 0 4px;font-size:13px;line-height:20px;color:${C.muted};">The Cupel team &middot; Reply to this email or write to <a href="mailto:team@cupel.in" style="color:${C.muted};text-decoration:underline;">team@cupel.in</a><br>${link(`${SITE}/terms`, "Terms")} &middot; ${link(`${SITE}/privacy`, "Privacy")} &middot; ${link(`${SITE}/refunds`, "Refunds")}</td></tr>
</table></td></tr></table></body></html>`;
}

/** The subject, plain text and HTML of one email (see content). */
export function compose(kind, d = {}, now = Date.now()) {
  const c = content(kind, d, now);
  return { subject: c.subject, text: `${c.paragraphs[0]}\n\n${c.paragraphs[1]} ${c.button.href}\n\n${SIGN_OFF}`, html: html(c) };
}

/** One message through Resend's HTTP API. Throws unless Resend accepts it. */
export async function resendSend(fetchFn, apiKey, { to, subject, text, html }, idempotencyKey) {
  const response = await fetchFn("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ from: FROM, to: [to], subject, text, html }),
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
