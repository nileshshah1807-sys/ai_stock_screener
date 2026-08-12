"use server";

import { headers } from "next/headers";

import { createClient } from "@/lib/supabase/server";

export type LoginState = {
  status: "idle" | "sent" | "error";
  message?: string;
  email?: string;
};

/**
 * Send a magic link.
 *
 * `shouldCreateUser: false` is the invite gate's first line: Supabase will not
 * provision an account for an unknown address, so an uninvited person cannot
 * even reach the signed-in-but-unauthorized state. The allowlist table and RLS
 * remain the authoritative checks behind it.
 *
 * The response is deliberately identical whether or not the address is known.
 * Saying "no such user" would turn this form into an oracle for which
 * addresses have access.
 */
export async function requestMagicLink(
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
  const headerList = await headers();
  const origin =
    process.env.NEXT_PUBLIC_SITE_URL ??
    `https://${headerList.get("host") ?? "localhost:3000"}`;

  const { error } = await supabase.auth.signInWithOtp({
    email,
    options: {
      shouldCreateUser: false,
      emailRedirectTo: `${origin}/auth/callback`,
    },
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
    message: "If that address has access, a sign-in link is on its way.",
  };
}

export async function signOut() {
  const supabase = await createClient();
  await supabase.auth.signOut();
}
