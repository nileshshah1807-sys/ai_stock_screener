import { NextResponse, type NextRequest } from "next/server";

import { safeNext } from "@/lib/login-code.mjs";
import { createClient } from "@/lib/supabase/server";

/**
 * Sign-in landing route. Establishes the session cookie from a one-time
 * credential, accepting both forms Supabase issues:
 *
 *   ?code=...        PKCE, produced by signInWithOtp from the login form
 *   ?token_hash=...  OTP,  from the email template and the admin generate_link API;
 *                    handed to /auth/confirm, which verifies it on a click
 *
 * The second matters because the admin API's `action_link` uses the implicit
 * flow, which returns the session in a URL *fragment* (`#access_token=...`).
 * Fragments are never sent to the server, so a server-side route cannot read
 * one. Verifying `token_hash` here instead keeps the whole exchange on the
 * server and works regardless of which flow minted the link.
 */
/**
 * Map Supabase's error codes onto the reasons the login page explains.
 *
 * Supabase reports a rejected link by redirecting here with `error` query
 * parameters rather than by failing the request, so a route that only looks
 * for a credential sees an empty query and reports the wrong cause -- telling
 * someone their link was malformed when it had simply already been used.
 */
function mapAuthError(errorCode: string | null, error: string | null): string {
  if (errorCode === "otp_expired") return "expired";
  if (errorCode === "access_denied" || error === "access_denied") return "denied";
  return "invalid_link";
}

export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl;
  const code = searchParams.get("code");
  const tokenHash = searchParams.get("token_hash");
  const rawType = searchParams.get("type");
  const next = searchParams.get("next") ?? "/";

  // Check for a reported failure before looking for a credential: when
  // Supabase rejects a link it sends these instead of one, and its reason is
  // more specific than anything this route could infer.
  const errorParam = searchParams.get("error");
  const errorCode = searchParams.get("error_code");
  if (errorParam || errorCode) {
    return NextResponse.redirect(
      `${origin}/login?error=${mapAuthError(errorCode, errorParam)}`,
    );
  }

  const supabase = await createClient();
  let failed = false;

  if (code) {
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    failed = Boolean(error);
  } else if (tokenHash) {
    // Not verified here: a mail scanner that opens the link would spend the
    // one-time token (and the code beside it) before the person clicks.
    // The confirm page verifies it when its button is pressed.
    const to = new URL("/auth/confirm", origin);
    to.searchParams.set("token_hash", tokenHash);
    if (rawType) to.searchParams.set("type", rawType);
    to.searchParams.set("next", safeNext(next));
    return NextResponse.redirect(to);
  } else {
    // No credential in the query. Supabase's implicit flow puts the session in
    // the URL fragment, which never reaches the server, so an empty query here
    // is far more likely to be a fragment-carrying link than a broken one.
    // Hand off to a browser page that can actually read it.
    //
    // Browsers re-apply the original fragment when a redirect target carries
    // none of its own, so `#access_token=...` survives this hop.
    return NextResponse.redirect(`${origin}/auth/complete`);
  }

  if (failed) {
    return NextResponse.redirect(`${origin}/login?error=invalid_link`);
  }

  // Only same-origin relative paths are honoured, so a crafted `next` cannot
  // turn the sign-in flow into an open redirect to an attacker's page.
  const destination = safeNext(next);
  return NextResponse.redirect(`${origin}${destination}`);
}
