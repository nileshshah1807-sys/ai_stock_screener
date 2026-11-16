// Pure helpers for Google sign-in (the button and One Tap), so node --test covers them.

import { safeNext } from "./login-code.mjs";

/** Once per tab: a dismissed prompt is not offered again on the next page. */
export const ONE_TAP_SHOWN_KEY = "cupel:one-tap-shown";

/**
 * Where Google's redirect lands after the button: the callback exchanges the
 * code and runs the trial guard, as for an email link.
 */
export function oauthRedirectTo(origin, next) {
  return `${origin}/auth/callback?next=${encodeURIComponent(safeNext(next))}`;
}

/**
 * After One Tap has set the session in the browser: the callback runs the
 * trial guard for it, then follows `next`.
 */
export function oneTapLanding(next) {
  return `/auth/callback?via=one_tap&next=${encodeURIComponent(safeNext(next))}`;
}

const hex = (bytes) => [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");

/**
 * A fresh nonce: Google signs the SHA-256 of it into the ID token, and
 * Supabase is given the raw value to check that hash, so a token lifted from
 * another page cannot be replayed here.
 */
export async function oneTapNonce(cryptoImpl = globalThis.crypto) {
  const raw = hex(cryptoImpl.getRandomValues(new Uint8Array(32)));
  const digest = await cryptoImpl.subtle.digest("SHA-256", new TextEncoder().encode(raw));
  return { raw, hashed: hex(new Uint8Array(digest)) };
}
