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
 * real gate: it verifies the token with Supabase and confirms the account is on
 * the invite list. RLS enforces the same rule at the database, so a route that
 * forgets to call this leaks nothing -- it just renders an empty page.
 *
 * Wrapped in React's cache() so several Server Components in one render share
 * a single verification round trip.
 */
export const getViewer = cache(async (): Promise<Viewer | null> => {
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user?.email) {
    return null;
  }

  // Readable under the allowlist self-read policy. A signed-in but uninvited
  // user gets zero rows here, which is what distinguishes "not invited" from
  // "not signed in" -- the two need different messages.
  const { data } = await supabase
    .from("dashboard_allowlist")
    .select("email, role")
    .ilike("email", user.email)
    .maybeSingle();

  if (!data) {
    return null;
  }

  return {
    id: user.id,
    email: user.email,
    role: (data.role as AccessLevel) ?? "viewer",
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
