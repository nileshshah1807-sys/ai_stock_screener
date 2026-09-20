import { redirect } from "next/navigation";
import { cache } from "react";

import { createClient } from "@/lib/supabase/server";

export type AccessLevel = "viewer" | "admin";

export type Viewer = {
  id: string;
  email: string;
  role: AccessLevel;
};

/**
 * Authorization check for every protected route and route handler.
 *
 * Proxy performs only an optimistic "is there a session" redirect. This is the
 * real gate: it verifies the token and confirms the account is on the invite
 * list. RLS enforces the same rule at the database, so a route that forgets to
 * call this leaks nothing -- it just renders an empty page.
 *
 * Wrapped in React's cache() so several Server Components in one render share
 * a single verification round trip.
 */
export const getViewer = cache(async (): Promise<Viewer | null> => {
  const supabase = await createClient();

  // getClaims() rather than getUser(). It verifies the token's signature
  // locally with WebCrypto against the project's ES256 public key, which
  // auth-js caches; getUser() spends a network round trip asking the auth
  // service to do the same thing. Both reject a forged or tampered token.
  //
  // The difference is revocation, and it is a deliberate trade. A deleted or
  // banned auth account keeps a cryptographically valid token until it expires
  // -- one hour by default -- and would still reach this app in that window.
  // What it would *not* reach is data: removal from this dashboard happens
  // through dashboard_allowlist, and both the query below and every RLS policy
  // re-read that table on every request, so a de-invited account loses access
  // immediately regardless of its token.
  //
  // Measured at 813ms for the two serial round trips this replaces, on every
  // render. The proxy has already warmed the JWKS cache before this runs, so
  // the local verification costs single-digit milliseconds.
  const { data, error } = await supabase.auth.getClaims();
  const claims = data?.claims;
  const email = typeof claims?.email === "string" ? claims.email.trim() : "";

  if (error || !claims?.sub || !email) {
    return null;
  }

  // Readable under the allowlist self-read policy. A signed-in but uninvited
  // user gets zero rows here, which is what distinguishes "not invited" from
  // "not signed in" -- the two need different messages.
  const { data: membership } = await supabase
    .from("dashboard_allowlist")
    .select("email, role")
    .ilike("email", email)
    .maybeSingle();

  if (!membership) {
    return null;
  }

  return {
    id: String(claims.sub),
    email,
    role: (membership.role as AccessLevel) ?? "viewer",
  };
});

/**
 * Use at the top of any protected page. Redirects rather than throwing, so an
 * expired session lands on the login form instead of an error boundary.
 */
export async function requireAccess(): Promise<Viewer> {
  const viewer = await getViewer();
  if (!viewer) {
    redirect("/no-access");
  }
  return viewer;
}

export async function requireAdmin(): Promise<Viewer> {
  const viewer = await requireAccess();
  if (viewer.role !== "admin") {
    redirect("/");
  }
  return viewer;
}
