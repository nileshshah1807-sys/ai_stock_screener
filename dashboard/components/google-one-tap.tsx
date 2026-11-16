"use client";

import { useEffect } from "react";

import { hasSession } from "@/components/landing/visitor-swap";
import { ONE_TAP_SHOWN_KEY, oneTapLanding, oneTapNonce } from "@/lib/google-sign-in.mjs";
import { createClient } from "@/lib/supabase/client";

const CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
const SCRIPT = "https://accounts.google.com/gsi/client";

type GoogleId = {
  initialize: (options: Record<string, unknown>) => void;
  prompt: () => void;
};

/**
 * Google One Tap on a signed-out page: one prompt per tab, never for a visitor
 * holding a session, and nothing at all without a client id. The browser signs
 * in with the ID token (no server work), then /auth/callback runs the trial
 * guard. Google also backs off by itself after a dismissal.
 */
export function GoogleOneTap({ next = null }: { next?: string | null }) {
  useEffect(() => {
    if (!CLIENT_ID || hasSession() || shownThisTab()) return;
    let cancelled = false;
    const script = document.createElement("script");
    script.src = SCRIPT;
    script.async = true;
    script.onload = async () => {
      const google = (window as unknown as { google?: { accounts?: { id?: GoogleId } } }).google?.accounts?.id;
      if (cancelled || !google) return;
      const nonce = await oneTapNonce();
      google.initialize({
        client_id: CLIENT_ID,
        nonce: nonce.hashed,
        auto_select: false,
        cancel_on_tap_outside: true,
        use_fedcm_for_prompt: true,
        itp_support: true,
        callback: async ({ credential }: { credential: string }) => {
          const { error } = await createClient().auth.signInWithIdToken({ provider: "google", token: credential, nonce: nonce.raw });
          if (error) console.error("Google One Tap sign-in failed", error.message);
          else window.location.assign(oneTapLanding(next));
        },
      });
      markShown();
      google.prompt();
    };
    document.head.appendChild(script);
    return () => {
      cancelled = true;
      script.remove();
    };
  }, [next]);

  return null;
}

function shownThisTab() {
  try {
    return sessionStorage.getItem(ONE_TAP_SHOWN_KEY) === "1";
  } catch {
    return false;
  }
}

function markShown() {
  try {
    sessionStorage.setItem(ONE_TAP_SHOWN_KEY, "1");
  } catch {
    // Storage blocked: Google's own cooldown still stops a repeat.
  }
}
