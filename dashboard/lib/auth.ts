import { redirect } from "next/navigation";
import { cache } from "react";

import { accessFromClaims, isEntitled } from "@/lib/billing.mjs";
import { isSessionExpired } from "@/lib/session-policy.mjs";
import { createClient } from "@/lib/supabase/server";

export type AccessLevel = "viewer" | "admin";

export type Access = ReturnType<typeof accessFromClaims>;

export type Viewer = {
  id: string;
  email: string;
  role: AccessLevel;
  /** What the token says the plan allows; "legacy" for a token issued before plans. */
  access: Access;
};

export type Session = { id: string; email: string; access: Access };

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
/**
 * Who is signed in and what their plan allows, whether or not it still allows
 * anything. The pricing and account pages need a lapsed person too: they are
 * where a lapsed person goes. Everything else asks getViewer().
 */
export const getSession = cache(async (): Promise<Session | null> => {
  const supabase = await createClient();

  // getClaims() rather than getUser(). It verifies the token's signature
  // locally with WebCrypto against the project's ES256 public key, which
  // auth-js caches; getUser() spends a network round trip asking the auth
  // service to do the same thing. Both reject a forged or tampered token.
  //
  // The difference is revocation, and it is a deliberate trade. A deleted or
  // banned auth account keeps a cryptographically valid token until it expires
  // -- one hour by default -- and would still reach this app in that window.
  // What it would *not* reach is data: every RLS policy re-reads the
  // subscription (or, for a token with no plan claim, dashboard_allowlist) on
  // every request, so an account that loses access loses it immediately
  // regardless of its token.
  const { data, error } = await supabase.auth.getClaims();
  const claims = data?.claims;
  const email = typeof claims?.email === "string" ? claims.email.trim() : "";

  if (error || !claims?.sub || !email) {
    return null;
  }

  // The proxy ends an over-age session before a page renders. Repeated here
  // because this is the gate route handlers and actions rely on, and a session
  // can cross its limit between the two checks.
  if (isSessionExpired(claims)) {
    return null;
  }

  return { id: String(claims.sub), email, access: accessFromClaims(claims) };
});

/**
 * Authorization for every protected route and route handler.
 *
 * Proxy performs only an optimistic "is there a session" redirect. This is the
 * real gate. A token with a plan claim is judged by it (admin, invited, trial
 * or paid, and still in date); a token without one predates plans and is
 * judged by the invite list, as it always was. RLS enforces the same rule at
 * the database, so a route that forgets to call this leaks nothing -- it just
 * renders an empty page.
 *
 * Wrapped in React's cache() so several Server Components in one render share
 * a single verification round trip.
 */
export const getViewer = cache(async (): Promise<Viewer | null> => {
  const session = await getSession();
  if (!session || !isEntitled(session.access)) {
    return null;
  }
  const { id, email, access } = session;

  if (access.kind !== "legacy") {
    return { id, email, role: access.kind === "admin" ? "admin" : "viewer", access };
  }

  // Readable under the allowlist self-read policy. A signed-in but uninvited
  // user gets zero rows here, which is what distinguishes "not invited" from
  // "not signed in" -- the two need different messages.
  const supabase = await createClient();
  const { data: membership } = await supabase
    .from("dashboard_allowlist")
    .select("email, role")
    .ilike("email", email)
    .maybeSingle();

  if (!membership) {
    return null;
  }

  return { id, email, role: (membership.role as AccessLevel) ?? "viewer", access };
});

/**
 * Use at the top of any protected page. Redirects rather than throwing, so an
 * expired session lands on the login form instead of an error boundary.
 */
export async function requireAccess(): Promise<Viewer> {
  const viewer = await getViewer();
  if (!viewer) {
    // A signed-in person whose plan has run out is sent to buy one, not told
    // they were never invited.
    const session = await getSession();
    redirect(session?.access.kind === "lapsed" ? "/pricing?lapsed=1" : "/no-access");
  }
  return viewer;
}

/** Buy/sell ratings and the Returns page are admin-only (lib/ratings.mjs). */
export async function isAdmin(): Promise<boolean> {
  return (await getViewer())?.role === "admin";
}

export async function requireAdmin(): Promise<Viewer> {
  const viewer = await requireAccess();
  if (viewer.role !== "admin") {
    redirect("/screener");
  }
  return viewer;
}
