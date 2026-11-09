/**
 * The Help & Support form: validation, the Jira Service Management (JSM) request
 * and the route's whole decision, so the route is a thin wrapper and this file is
 * what the tests drive. No Next.js import here.
 */

export const CATEGORIES = ["Billing & plans", "Data question", "Account", "Feature idea", "Something else"];

export const LIMITS = { name: 100, subject: 150, message: 5000, messageMin: 10 };

const ENV_KEYS = ["JSM_SITE", "JSM_EMAIL", "JSM_API_TOKEN", "JSM_SERVICE_DESK_ID", "JSM_REQUEST_TYPE_ID"];

/** The largest request body the route reads (the message limit plus the other fields). */
export const MAX_BODY_BYTES = 10 * 1024;

/** One line: control characters out, white space collapsed. */
const oneLine = (value) => String(value ?? "").replace(/[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/gu, " ").replace(/\s+/g, " ").trim();

/** True when every JSM variable is set; the form falls back to a mailto link otherwise. */
export const supportConfigured = (env) => ENV_KEYS.every((key) => Boolean(env[key]?.trim()));

/**
 * `email` is the signed-in user's session email, never the body's: JSM emails
 * whoever raiseOnBehalfOf names, so a typed address would let anyone mail a stranger.
 * @returns {{ok: true, value: {name: string, email: string, subject: string, message: string, category: string}} | {ok: false, error: string}}
 */
export function validateSupport(body, email) {
  const input = body && typeof body === "object" ? body : {};
  const name = oneLine(input.name);
  const subject = oneLine(input.subject);
  const message = String(input.message ?? "").replace(/\r\n?/g, "\n").replace(/[^\P{Cc}\n\t]/gu, "").trim();
  const category = CATEGORIES.includes(input.category) ? input.category : null;

  if (!name || name.length > LIMITS.name) return { ok: false, error: "Enter your name (up to 100 characters)." };
  if (!category) return { ok: false, error: "Choose a category." };
  if (subject.length < 3 || subject.length > LIMITS.subject) return { ok: false, error: "Give a subject of 3 to 150 characters." };
  if (message.length < LIMITS.messageMin || message.length > LIMITS.message) {
    return { ok: false, error: `Write a message of ${LIMITS.messageMin} to ${LIMITS.message} characters.` };
  }
  return { ok: true, value: { name, email, subject, message, category } };
}

/**
 * Per-address limiter held in this server instance's memory.
 * shortcut: serverless instances do not share it, so the real ceiling is per
 * instance; move to a database counter if the form is ever abused.
 */
export function createLimiter({ max = 5, windowMs = 10 * 60 * 1000 } = {}) {
  const hits = new Map();
  return (key, now = Date.now()) => {
    const recent = (hits.get(key) ?? []).filter((at) => now - at < windowMs);
    if (recent.length >= max) {
      hits.set(key, recent);
      return false;
    }
    hits.set(key, [...recent, now]);
    if (hits.size > 5000) for (const [k, v] of hits) if (v.every((at) => now - at >= windowMs)) hits.delete(k);
    return true;
  };
}

/** JSM_SITE may be the subdomain ("cupel") or the full host ("cupel.atlassian.net"). */
const jsmHost = (site) => (site.includes(".") ? site : `${site}.atlassian.net`).replace(/^https?:\/\//, "").replace(/\/+$/, "");

/** What JSM said about a refusal, for the server log: status and its own error fields, never the request. */
async function refusal(response) {
  const detail = await response.json().catch(() => ({}));
  return { status: response.status, errorMessage: detail.errorMessage, errors: detail.errors };
}

/**
 * Opens the customer request; JSM emails the customer and threads their replies.
 * A desk that only lets "customers I add" raise requests refuses an email it does
 * not know, so on a 4xx the customer is added and the request tried once more.
 */
export async function createJsmRequest(fetchImpl, env, { name, email, subject, message, category }, log = console) {
  const base = `https://${jsmHost(env.JSM_SITE.trim())}/rest/servicedeskapi`;
  const headers = {
    Authorization: `Basic ${Buffer.from(`${env.JSM_EMAIL}:${env.JSM_API_TOKEN}`).toString("base64")}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  const post = (path, payload) => fetchImpl(`${base}${path}`, { method: "POST", headers, body: JSON.stringify(payload), signal: AbortSignal.timeout(8000) });
  const open = () =>
    post("/request", {
      serviceDeskId: env.JSM_SERVICE_DESK_ID.trim(),
      requestTypeId: env.JSM_REQUEST_TYPE_ID.trim(),
      raiseOnBehalfOf: email,
      requestFieldValues: { summary: subject, description: `From: ${name} <${email}>\nCategory: ${category}\n\n${message}` },
    });

  let response = await open();
  if (response.ok) return;
  const first = await refusal(response);
  log.error("support: JSM refused the request", first);
  if (first.status < 400 || first.status >= 500) throw new Error(`JSM answered ${first.status}`);

  const customer = await post("/customer", { email, displayName: name });
  // An existing customer is refused here too; that is fine, the retry decides.
  if (!customer.ok) log.error("support: JSM customer step", await refusal(customer));
  response = await open();
  if (response.ok) return;
  log.error("support: JSM refused the retry", await refusal(response));
  throw new Error(`JSM answered ${response.status}`);
}

/**
 * The route's decision; `keys` are what the limiter counts (address and account); `email` is the session's, null when signed out. Statuses:
 * 200 sent, 400 invalid, 401 signed out, 429 too many, 502 JSM failed, 503 not
 * configured (the page then shows the mailto fallback).
 * A filled honeypot ("website") gets a 200 and nothing is sent.
 */
export async function submitSupport({ body, email, env, keys, limiter, fetchImpl = fetch, log = console }) {
  if (!supportConfigured(env)) return { status: 503, body: { error: "not_configured" } };
  if (!email) return { status: 401, body: { error: "sign_in" } };
  if (body && typeof body === "object" && body.website) return { status: 200, body: { ok: true } };
  if (!keys.map((key) => limiter(key)).every(Boolean)) return { status: 429, body: { error: "Too many messages from this address. Try again in a few minutes." } };
  const checked = validateSupport(body, email);
  if (!checked.ok) return { status: 400, body: { error: checked.error } };
  try {
    await createJsmRequest(fetchImpl, env, checked.value, log);
  } catch (error) {
    log.error("support: could not open the JSM request", error instanceof Error ? error.message : error);
    return { status: 502, body: { error: "send_failed" } };
  }
  return { status: 200, body: { ok: true } };
}
