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

  // getUser() revalidates the token against Supabase. getSession() only decodes
  // the cookie, which a client could have forged, so it must not gate routing.
  //
  // A network failure here must not 500 every route. Treating an unreachable
  // auth service as "no session" fails closed: the request is sent to the login
  // page rather than through to data, and RLS would refuse the read anyway.
  let user = null;
  try {
    const result = await supabase.auth.getUser();
    user = result.data.user;
  } catch (error) {
    console.error("Auth check failed in proxy", error);
  }

  const { pathname, search } = request.nextUrl;
  const isPublicRoute =
    pathname.startsWith("/login") || pathname.startsWith("/auth");

  if (!user && !isPublicRoute) {
    const redirectUrl = request.nextUrl.clone();
    redirectUrl.pathname = "/login";
    // Preserve the destination so a deep link survives the login round trip.
    redirectUrl.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(redirectUrl);
  }

  if (user && pathname.startsWith("/login")) {
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
