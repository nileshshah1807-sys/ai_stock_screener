/**
 * How long a sign-in lasts.
 *
 * Supabase refreshes a session for as long as its refresh token keeps being
 * presented, so without a rule of our own one magic link signs a browser in
 * forever. The rule here is an absolute lifetime measured from the moment of
 * authentication: once it has passed, the session ends no matter how recently
 * it was used, and the next visit asks for a fresh link.
 *
 * The clock is the `amr` claim. Supabase records each authentication method
 * with the time it happened, inside the signed access token, and carries that
 * entry unchanged across every refresh. `iat` would not do -- it is the time
 * the *token* was minted and moves forward on each refresh, which is exactly
 * the behaviour being bounded. Reading the age from a signed claim also means
 * the browser cannot extend it, which a cookie of our own could not promise
 * without a server secret this app does not otherwise need.
 *
 * Plain .mjs so `node --test` covers it without a build step, like the other
 * pure modules in this directory.
 */

const HOUR_SECONDS = 60 * 60;

/** Seven days: a working week on one link, and a lost laptop is not a standing key. */
export const DEFAULT_SESSION_MAX_AGE_HOURS = 24 * 7;

/**
 * Lifetime in seconds, from SESSION_MAX_AGE_HOURS when it holds a positive
 * number. Anything else falls back to the default rather than to "no limit":
 * a typo in an environment variable must not quietly restore endless sessions.
 */
export function sessionMaxAgeSeconds(raw = process.env.SESSION_MAX_AGE_HOURS) {
  const hours = Number(raw);
  const valid =
    typeof raw === "string" && raw.trim() !== "" && Number.isFinite(hours) && hours > 0;
  return Math.round((valid ? hours : DEFAULT_SESSION_MAX_AGE_HOURS) * HOUR_SECONDS);
}

/**
 * When this session was authenticated, in epoch seconds, or null when the
 * token does not say.
 *
 * The earliest entry, not the first or the latest: a later step-up (an MFA
 * challenge, say) appends its own entry, and it should not restart the clock.
 */
export function sessionStartedAt(claims) {
  const entries = Array.isArray(claims?.amr) ? claims.amr : [];
  const times = entries
    .map((entry) => Number(entry?.timestamp))
    .filter((time) => Number.isFinite(time) && time > 0);
  return times.length ? Math.min(...times) : null;
}

/**
 * True when the session has outlived its lifetime.
 *
 * A token with no readable authentication time counts as expired. Its age is
 * unknown, and letting it through would make the limit something a session
 * escapes by lacking the evidence.
 */
export function isSessionExpired(
  claims,
  nowSeconds = Date.now() / 1000,
  maxAgeSeconds = sessionMaxAgeSeconds(),
) {
  const startedAt = sessionStartedAt(claims);
  if (startedAt === null) return true;
  return nowSeconds - startedAt >= maxAgeSeconds;
}
