/**
 * The names of Supabase's session cookies in a `document.cookie` string:
 * sb-<project>-auth-token, and its .0/.1 chunks when the session is large.
 *
 * @param {string} cookie
 * @returns {string[]}
 */
export function authCookieNames(cookie) {
  return cookie
    .split(";")
    .map((part) => part.split("=")[0].trim())
    .filter((name) => /^sb-[^=]+-auth-token(\.\d+)?$/.test(name));
}

/** @param {string} name Expiring each one at path "/" (where @supabase/ssr sets them) signs the browser out locally. */
export const expireCookie = (name) => `${name}=; Max-Age=0; path=/; SameSite=Lax`;
