import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

/**
 * Next.js 16 renamed Middleware to Proxy. Same execution model: this runs
 * before the request completes.
 *
 * Its job here is deliberately narrow, per the Next.js guidance that Proxy is
 * not a session-management or authorization solution:
 *
 *   1. refresh the Supabase auth token and write the rotated cookies
 *   2. perform an *optimistic* redirect for requests with no session at all
 *
 * It does not decide whether a signed-in user is on the invite list. That
 * check lives in requireAccess() (lib/auth.ts) and, authoritatively, in the
 * RLS policies. A user who authenticates but is not invited reaches the app
 * and is told so; they cannot read any row.
 */
export async function proxy(request: NextRequest) {
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
  const authStarted = performance.now();
  try {
    const { data, error } = await supabase.auth.getClaims();
    signedIn = !error && Boolean(data?.claims?.sub);
  } catch (error) {
    console.error("Auth check failed in proxy", error);
  }
  if (process.env.SCREENER_TRACE === "1") {
    console.log(
      `      [trace] proxy auth.getClaims      ${(performance.now() - authStarted).toFixed(0).padStart(6)} ms  ${request.nextUrl.pathname}${request.nextUrl.search}`,
    );
  }

  const { pathname, search } = request.nextUrl;
  const isPublicRoute =
    pathname.startsWith("/login") || pathname.startsWith("/auth");

  if (!signedIn && !isPublicRoute) {
    const redirectUrl = request.nextUrl.clone();
    redirectUrl.pathname = "/login";
    // Preserve the destination so a deep link survives the login round trip.
    redirectUrl.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(redirectUrl);
  }

  if (signedIn && pathname.startsWith("/login")) {
    const redirectUrl = request.nextUrl.clone();
    redirectUrl.pathname = "/";
    redirectUrl.search = "";
    return NextResponse.redirect(redirectUrl);
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
