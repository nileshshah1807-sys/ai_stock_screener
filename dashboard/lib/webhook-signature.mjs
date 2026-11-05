/**
 * Server only: imported by the Razorpay webhook route alone, never by a client
 * component, so node:crypto stays out of the browser bundle (lib/billing.mjs is
 * imported by client code).
 */

import { createHmac, timingSafeEqual } from "node:crypto";

/** The Razorpay webhook signature: hex HMAC-SHA256 of the raw body. */
export function verifySignature(rawBody, signature, secret) {
  if (!secret || typeof signature !== "string" || !signature) return false;
  const expected = createHmac("sha256", secret).update(rawBody).digest("hex");
  const given = Buffer.from(signature, "utf8");
  const wanted = Buffer.from(expected, "utf8");
  return given.length === wanted.length && timingSafeEqual(given, wanted);
}
