/**
 * Who may see a page served as a static file (the browser shell,
 * components/browser-shell.tsx) or read the objects it shows (lib/object-gate.mjs),
 * from the session token's claims. The same rule as the proxy's redirect and
 * requireAccess() (lib/auth.ts), which a static page never reaches: no session goes
 * to /login, an over-age one to /login with `session_expired`, a lapsed plan to
 * /pricing. A token with no plan claim predates the access hook; the shell
 * refreshes it once and refuses it after that.
 */

import { accessFromClaims, isEntitled } from "./billing.mjs";
import { isSessionExpired } from "./session-policy.mjs";

/** The login page, keeping the destination as the proxy does. */
export function loginPath(next, expired = false) {
  const query = new URLSearchParams({ next });
  if (expired) query.set("error", "session_expired");
  return `/login?${query}`;
}

/**
 * @param {Record<string, unknown> | null | undefined} claims a verified (or, in the browser, the session's) token payload
 * @param {string} path the page asked for, path and query
 * @returns {{ kind: "viewer", viewer: { id: string, email: string, role: "admin" | "viewer", access: ReturnType<typeof accessFromClaims> } }
 *   | { kind: "redirect", to: string, signOut?: boolean } | { kind: "legacy" }}
 */
export function shellAccess(claims, path, nowSeconds = Date.now() / 1000) {
  const email = typeof claims?.email === "string" ? claims.email.trim() : "";
  if (!claims?.sub || !email) return { kind: "redirect", to: loginPath(path) };
  if (isSessionExpired(claims, nowSeconds)) return { kind: "redirect", to: loginPath(path, true), signOut: true };
  const access = accessFromClaims(claims, nowSeconds);
  if (access.kind === "legacy") return { kind: "legacy" };
  if (!isEntitled(access)) return { kind: "redirect", to: "/pricing?lapsed=1" };
  const role = access.kind === "admin" ? "admin" : "viewer";
  return { kind: "viewer", viewer: { id: String(claims.sub), email, role, access } };
}
