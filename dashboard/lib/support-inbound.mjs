/**
 * Mail to the support address becomes a JSM ticket: Resend's `email.received`
 * webhook, checked and turned into the same request the Help form opens
 * (createJsmRequest in support.mjs). The webhook carries ids only, so the text is
 * fetched from Resend. No Next.js import here; the route supplies the claim table.
 */
import { createHmac, timingSafeEqual } from "node:crypto";

import { LIMITS, createJsmRequest, oneLine, supportConfigured } from "./support.mjs";

const TOLERANCE_SECONDS = 5 * 60;

/** A claim not completed within this is taken as a crashed or timed-out call and may be taken over. */
export const STALE_CLAIM_MS = 5 * 60 * 1000;

/**
 * Takes an email for this call. The store is the table's two moves: `insert` (true
 * if the id was new) and `reclaim` (true if it took over an unfinished claim older
 * than `staleBefore`). A finished email is never taken twice.
 */
export const claimEmail = async (store, emailId, now = Date.now()) =>
  (await store.insert(emailId, now)) || (await store.reclaim(emailId, now - STALE_CLAIM_MS, now));

/** Why a message must not open a ticket, or null. Auto replies would otherwise answer each other forever. */
export function automatedReason(headers = {}) {
  const h = Object.fromEntries(Object.entries(headers).map(([k, v]) => [k.toLowerCase(), String(v).trim().toLowerCase()]));
  if (h["auto-submitted"] && h["auto-submitted"] !== "no") return "auto-submitted";
  if (["bulk", "junk", "list", "auto_reply"].includes(h.precedence)) return "precedence";
  if ("x-autoreply" in h || "x-autorespond" in h || "x-auto-response-suppress" in h) return "auto-response header";
  if (h["return-path"] === "<>") return "bounce";
  return null;
}

/** Resend signs with the Svix scheme: HMAC-SHA256 of `id.timestamp.body`, base64, `v1,` prefixed, space separated. */
export function verifySignature({ secret, id, timestamp, signature, body, now = Date.now() }) {
  if (!secret || !id || !timestamp || !signature) return false;
  if (!(Math.abs(now / 1000 - Number(timestamp)) <= TOLERANCE_SECONDS)) return false;
  const key = Buffer.from(secret.trim().replace(/^whsec_/, ""), "base64");
  const want = createHmac("sha256", key).update(`${id}.${timestamp}.${body}`).digest();
  return signature.split(" ").some((part) => {
    const [version, value] = part.split(",");
    const got = Buffer.from(value ?? "", "base64");
    return version === "v1" && got.length === want.length && timingSafeEqual(got, want);
  });
}

/** "Name <a@b.c>" or "a@b.c" as a lower-case bare address. */
const bare = (value) => (/<([^>]+)>/.exec(String(value))?.[1] ?? String(value)).trim().toLowerCase();

const stripTags = (html) => html.replace(/<(style|script)[\s\S]*?<\/\1>/gi, " ").replace(/<[^>]+>/g, " ").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&");

async function fetchBody(fetchImpl, apiKey, emailId) {
  const response = await fetchImpl(`https://api.resend.com/emails/receiving/${encodeURIComponent(emailId)}`, {
    headers: { Authorization: `Bearer ${apiKey}` },
    signal: AbortSignal.timeout(8000),
  });
  if (!response.ok) throw new Error(`Resend answered ${response.status}`);
  return response.json();
}

/**
 * The route's decision. 401 unsigned or wrong, 503 not set up, 200 handled or
 * deliberately ignored (a retry would change nothing), 502 a failure Resend
 * should retry (the claim is given back first, and a failure to give it back is
 * only logged: the claim then goes stale and a retry takes it over). Once the ticket
 * exists nothing is retried: a failure to mark it complete is only logged.
 * `claim(emailId)` is true for the one caller that wins the email; `complete` marks
 * it done (a drop is done too: a retry would change nothing); `release` undoes a claim.
 */
export async function handleInbound({ rawBody, headers, env, supportAddress, claim, complete, release, fetchImpl = fetch, now = Date.now(), log = console }) {
  const secret = env.RESEND_INBOUND_WEBHOOK_SECRET;
  const apiKey = env.RESEND_API_KEY;
  if (!secret || !apiKey || !supportConfigured(env)) return { status: 503, body: { error: "not_configured" } };
  const signed = verifySignature({ secret, id: headers.get("svix-id"), timestamp: headers.get("svix-timestamp"), signature: headers.get("svix-signature"), body: rawBody, now });
  if (!signed) return { status: 401, body: { error: "bad_signature" } };

  let event;
  try {
    event = JSON.parse(rawBody);
  } catch {
    return { status: 400, body: { error: "bad_json" } };
  }
  const data = event?.data ?? {};
  const support = bare(supportAddress);
  const to = [...(data.to ?? []), ...(data.received_for ?? [])].map(bare);
  const sender = bare(data.from ?? "");
  // Our own address as sender would loop a ticket's notification back in.
  const ignore = event?.type !== "email.received" || !data.email_id || !to.includes(support) || !sender.includes("@") || sender === support;
  if (ignore) return { status: 200, body: { ignored: true } };

  if (!(await claim(data.email_id))) return { status: 200, body: { duplicate: true } };
  try {
    const mail = await fetchBody(fetchImpl, apiKey, data.email_id);
    // Fail closed: a forged From would have JSM write to a stranger, and an
    // unverifiable one cannot be told from a forged one.
    const dmarc = mail.authentication?.dmarc;
    const dropped = dmarc !== "pass" ? `dmarc ${dmarc ?? "absent"}` : automatedReason(mail.headers);
    if (dropped) {
      log.error("support inbound: dropped a message", { emailId: data.email_id, reason: dropped });
      await complete(data.email_id);
      return { status: 200, body: { ignored: true } };
    }
    const text = (mail.text ?? stripTags(mail.html ?? "")).replace(/\r\n?/g, "\n").replace(/[^\P{Cc}\n\t]/gu, "").trim();
    await createJsmRequest(
      fetchImpl,
      env,
      {
        name: sender,
        email: sender,
        subject: oneLine(mail.subject ?? data.subject).slice(0, LIMITS.subject) || "(no subject)",
        message: text.slice(0, LIMITS.message) || "(empty message)",
        category: "Email",
      },
      log,
    );
    // The ticket exists: a failure to mark it must not send Resend back for a second one.
    await Promise.resolve(complete(data.email_id)).catch((e) => log.error("support inbound: ticket made but could not be marked complete", e instanceof Error ? e.message : e));
  } catch (error) {
    log.error("support inbound: could not make the ticket", error instanceof Error ? error.message : error);
    await Promise.resolve(release(data.email_id)).catch((e) => log.error("support inbound: could not release the claim", e instanceof Error ? e.message : e));
    return { status: 502, body: { error: "failed" } };
  }
  return { status: 200, body: { ok: true } };
}
