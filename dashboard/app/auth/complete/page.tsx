"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, TriangleAlert } from "lucide-react";

import { createClient } from "@/lib/supabase/client";

/**
 * Completes a sign-in whose credential arrived in the URL fragment.
 *
 * Supabase's implicit flow returns the session as `#access_token=...`. A
 * fragment is never transmitted to the server, so the callback route cannot
 * see it -- the request arrives with an empty query and no way to tell a
 * fragment-carrying link from a malformed one. This page runs in the browser,
 * where the fragment is readable, hands the tokens to the Supabase client to
 * persist as cookies, and then continues into the app.
 *
 * It exists as a fallback rather than the main path: PKCE links from the login
 * form carry `?code=` and are exchanged server-side, which is preferable
 * because the token never touches the browser's address bar.
 */
export default function AuthCompletePage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const hash = window.location.hash.slice(1);
    if (!hash) {
      router.replace("/login?error=missing_code");
      return;
    }

    const params = new URLSearchParams(hash);

    // Supabase reports rejection in the fragment too, not only in the query.
    const errorCode = params.get("error_code");
    if (errorCode || params.get("error")) {
      const reason =
        errorCode === "otp_expired"
          ? "expired"
          : errorCode === "access_denied" || params.get("error") === "access_denied"
            ? "denied"
            : "invalid_link";
      router.replace(`/login?error=${reason}`);
      return;
    }

    const accessToken = params.get("access_token");
    const refreshToken = params.get("refresh_token");
    if (!accessToken || !refreshToken) {
      router.replace("/login?error=missing_code");
      return;
    }

    const supabase = createClient();
    supabase.auth
      .setSession({ access_token: accessToken, refresh_token: refreshToken })
      .then(({ error: sessionError }) => {
        if (sessionError) {
          setError(sessionError.message);
          router.replace("/login?error=invalid_link");
          return;
        }
        // Clear the tokens from the address bar before moving on, so they are
        // not left in history or leaked by a copied URL.
        window.history.replaceState(null, "", "/auth/complete");
        // A full navigation, not a client transition: the server needs to read
        // the freshly written cookies to render the authenticated page.
        window.location.replace("/");
      })
      .catch(() => router.replace("/login?error=invalid_link"));
  }, [router]);

  return (
    <main className="flex min-h-dvh items-center justify-center px-4">
      <div className="text-center" role="status" aria-live="polite">
        {error ? (
          <>
            <TriangleAlert
              className="mx-auto size-5 text-destructive"
              aria-hidden
            />
            <p className="mt-3 text-sm text-destructive">{error}</p>
          </>
        ) : (
          <>
            <Loader2
              className="mx-auto size-5 animate-spin text-muted-foreground"
              aria-hidden
            />
            <p className="mt-3 text-sm text-muted-foreground">Signing you in…</p>
          </>
        )}
      </div>
    </main>
  );
}
