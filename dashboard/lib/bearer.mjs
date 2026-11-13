import { timingSafeEqual } from "node:crypto";

/**
 * Whether an `Authorization` header carries `Bearer <secret>`, compared in
 * constant time. False when the secret is not configured, so an unset
 * variable never opens a route.
 *
 * @param {string | null} header
 * @param {string | undefined} secret
 */
export function bearerMatches(header, secret) {
  if (!secret) return false;
  const given = Buffer.from(header ?? "");
  const want = Buffer.from(`Bearer ${secret}`);
  return given.length === want.length && timingSafeEqual(given, want);
}
