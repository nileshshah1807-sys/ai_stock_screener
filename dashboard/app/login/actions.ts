"use server";

import { redirect } from "next/navigation";

import { isCode, normalizeCode, otpTypeOf, safeNext } from "@/lib/login-code.mjs";
import { createClient } from "@/lib/supabase/server";

export type LoginState = {
  status: "idle" | "sent" | "error";
  message?: string;
  email?: string;
};

/**
 * Email a sign-in code (and a link that opens the Continue page).
 *
 * `shouldCreateUser: true` is sign-up: an address Supabase has not seen gets
 * an account, and the database gives it a 7-day trial. The same code form
 * serves a returning person, so there is no separate sign-up path to guess at.
 *
 * The response is deliberately identical whether or not the address is known.
 * Saying "no such user" would turn this form into an oracle for which
 * addresses have access.
 */
export async function requestLoginCode(
  _prev: LoginState,
  formData: FormData,
): Promise<LoginState> {
  const email = String(formData.get("email") ?? "")
    .trim()
    .toLowerCase();

  if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    return { status: "error", message: "Enter a valid email address." };
  }

  const supabase = await createClient();

  // No redirect option: the email's link is built by the template, from the
  // project's Site URL, and lands on /auth/callback.
  const { error } = await supabase.auth.signInWithOtp({
    email,
    options: { shouldCreateUser: true },
  });

  // Rate limiting is worth surfacing: it is actionable ("wait and retry"),
  // unlike an unknown-address error, which is not disclosed.
  if (error && error.status === 429) {
    return {
      status: "error",
      message: "Too many requests. Wait a few minutes and try again.",
      email,
    };
  }

  return {
    status: "sent",
    email,
    message: "A 6-digit code is on its way.",
  };
}

export async function signOut() {
  const supabase = await createClient();
  await supabase.auth.signOut();
}

export type CodeState = { status: "idle" | "error"; message?: string };

/**
 * Check the code the person typed. The failure text is the same for a wrong,
 * spent or unknown-address code, for the reason requestLoginCode answers every
 * address alike.
 */
export async function verifyLoginCode(_prev: CodeState, formData: FormData): Promise<CodeState> {
  const email = String(formData.get("email") ?? "").trim().toLowerCase();
  const code = normalizeCode(formData.get("code"));
  if (!isCode(code)) return { status: "error", message: "Enter the 6-digit code from the email." };

  const supabase = await createClient();
  const { error } = await supabase.auth.verifyOtp({ email, token: code, type: "email" });
  if (error?.status === 429) {
    return { status: "error", message: "Too many attempts. Wait a few minutes and try again." };
  }
  if (error) {
    return { status: "error", message: "That code is wrong or has expired. Codes last 15 minutes and work once." };
  }
  redirect("/");
}

/** The Continue page's button: spends the link's one-time token only when pressed. */
export async function confirmLink(formData: FormData) {
  const tokenHash = String(formData.get("token_hash") ?? "");
  const type = otpTypeOf(String(formData.get("type") ?? ""));
  const next = safeNext(formData.get("next"));
  if (!tokenHash) redirect("/login?error=missing_code");
  const supabase = await createClient();
  const { error } = await supabase.auth.verifyOtp({ token_hash: tokenHash, type });
  if (error) redirect("/login?error=expired");
  redirect(next);
}
