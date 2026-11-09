import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

import { DEVICE_COOKIE } from "@/lib/device-cookie";
import { LEGAL_PAGES } from "@/lib/legal";
import { isSessionExpired } from "@/lib/session-policy.mjs";

/**
 * Next.js 16 renamed Middleware to Proxy. Same execution model: this runs
 * before the request completes.
 *
 * Its job here is deliberately narrow, per the Next.js guidance that Proxy is
 * not a session-management or authorization solution:
 *
 *   1. refresh the Supabase auth token and write the rotated cookies
 *   2. end a session that has outlived its lifetime (lib/session-policy.mjs)
 *   3. perform an *optimistic* redirect for requests with no session at all
 *
 * It does not decide whether a signed-in user is on the invite list. That
 * check lives in requireAccess() (lib/auth.ts) and, authoritatively, in the
 * RLS policies. A user who authenticates but is not invited reaches the app
 * and is told so; they cannot read any row.
 */
export async function proxy(request: NextRequest) {
  // A random id, set once, that lets the free-trial check (lib/trial-guard.ts)
  // recognise a browser that has already had a trial. Put on the request too, so
  // a route that runs on this very request can read it.
  const newDeviceId = request.cookies.has(DEVICE_COOKIE) ? null : crypto.randomUUID();
  if (newDeviceId) request.cookies.set(DEVICE_COOKIE, newDeviceId);
  let response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value),
          );
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options),
          );
        },
      },
    },
  );

  // getClaims() verifies the token's signature locally with WebCrypto against
  // the project's ES256 public key, which auth-js caches after the first fetch.
  // That is a real cryptographic check, not a bare decode of a
  // client-controlled cookie -- an unsigned or tampered token is rejected here
  // exactly as getUser() would reject it, without paying a network round trip
  // to the auth service on every single navigation.
  //
  // Token refresh still happens: getClaims() reads the session first, and that
  // read refreshes when the access token is inside its expiry margin. The
  // difference is that the refresh now costs a request only when one is
  // actually due, rather than once per navigation.
  //
  // This remains an *optimistic* gate either way. requireAccess() re-verifies
  // against the auth service and checks the invite list, and RLS refuses the
  // read regardless, so a forged cookie that somehow passed here would still
  // reach no data.
  //
  // A failure must not 500 every route. Treating an unusable token as "no
  // session" fails closed: the request goes to the login page rather than
  // through to data.
  let signedIn = false;
  let sessionExpired = false;
  const authStarted = performance.now();
  try {
    const { data, error } = await supabase.auth.getClaims();
    signedIn = !error && Boolean(data?.claims?.sub);
    sessionExpired = signedIn && isSessionExpired(data?.claims);
  } catch (error) {
    console.error("Auth check failed in proxy", error);
  }

  // Refreshing above would otherwise keep one sign-in alive indefinitely. Past
  // its lifetime the session is revoked at Supabase -- `local` scope, so only
  // this browser's session and not the same person's phone -- and the request
  // carries on as signed out.
  if (sessionExpired) {
    signedIn = false;
    let revoked = false;
    try {
      const { error } = await supabase.auth.signOut({ scope: "local" });
      revoked = !error;
    } catch (error) {
      console.error("Could not revoke an expired session in proxy", error);
    }
    if (!revoked) {
      // signOut() leaves the cookies in place when the auth service cannot be
      // reached. Drop them here regardless: the browser must not go on
      // presenting a session this app has stopped honouring.
      request.cookies
        .getAll()
        .filter(({ name }) => name.startsWith("sb-"))
        .forEach(({ name }) => response.cookies.delete(name));
    }
  }
  if (process.env.SCREENER_TRACE === "1") {
    console.log(
      `      [trace] proxy auth.getClaims      ${(performance.now() - authStarted).toFixed(0).padStart(6)} ms  ${request.nextUrl.pathname}${request.nextUrl.search}`,
    );
  }

  const { pathname, search } = request.nextUrl;
  // The legal pages and the price are public: a visitor reads them before
  // agreeing to them.
  const isPublicRoute =
    pathname.startsWith("/login") ||
    pathname.startsWith("/auth") ||
    pathname === "/pricing" ||
    // The help page and its form: someone locked out must be able to write.
    pathname === "/help" ||
    pathname === "/api/support" ||
    // Crawlers fetch these without signing in.
    pathname === "/robots.txt" ||
    pathname === "/sitemap.xml" ||
    // The landing page; /screener is the app's entry and stays behind sign-in.
    pathname === "/" ||
    // Razorpay's server calls this, not a browser; the route verifies the
    // payload's signature itself.
    pathname === "/api/billing/webhook" ||
    LEGAL_PAGES.some((page) => pathname === page.href);

  if (!signedIn && !isPublicRoute) {
    const redirectUrl = request.nextUrl.clone();
    redirectUrl.pathname = "/login";
    // Preserve the destination so a deep link survives the login round trip.
    redirectUrl.searchParams.set("next", `${pathname}${search}`);
    if (sessionExpired) {
      redirectUrl.searchParams.set("error", "session_expired");
    }
    const redirectResponse = NextResponse.redirect(redirectUrl);
    // The cleared auth cookies were written to `response`; a redirect is a new
    // object and would leave them behind.
    response.cookies.getAll().forEach((cookie) => redirectResponse.cookies.set(cookie));
    return redirectResponse;
  }

  if (signedIn && pathname.startsWith("/login")) {
    const redirectUrl = request.nextUrl.clone();
    redirectUrl.pathname = "/screener";
    redirectUrl.search = "";
    return NextResponse.redirect(redirectUrl);
  }

  if (newDeviceId) {
    response.cookies.set(DEVICE_COOKIE, newDeviceId, {
      httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production", path: "/", maxAge: 400 * 86_400,
    });
  }

  // Returning this exact response object matters: it carries the refreshed
  // auth cookies. Constructing a fresh NextResponse here would silently drop
  // them and log the user out on token rotation.
  return response;
}

export const config = {
  matcher: [
    /*
     * Everything except static assets and image files. Auth cookie refresh
     * must run on real navigations, not on every icon request.
     */
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};
