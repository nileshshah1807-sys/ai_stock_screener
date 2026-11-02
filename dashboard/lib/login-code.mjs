// Pure helpers for the email-code sign-in, so node --test covers them.

/** Supabase's email code length (Authentication, Email, "OTP length"); 6 unless the project changes it. */
export const CODE_LENGTH = 6;

/** What a person pastes ("123 456", "123-456 ") reduced to its digits. */
export function normalizeCode(input) {
  return String(input ?? "").replace(/\D/g, "");
}

export function isCode(input) {
  return normalizeCode(input).length === CODE_LENGTH;
}

const OTP_TYPES = new Set(["magiclink", "signup", "invite", "recovery", "email_change", "email"]);

/** The link's own type when Supabase knows it; `email` otherwise, which also verifies a magic-link token. */
export function otpTypeOf(raw) {
  return OTP_TYPES.has(raw) ? raw : "email";
}

/** Only a same-origin path is followed after sign-in, so `next` cannot be an open redirect. */
export function safeNext(next) {
  return typeof next === "string" && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/";
}
