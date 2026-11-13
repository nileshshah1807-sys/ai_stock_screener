"use client";

import { useSyncExternalStore, type ReactNode } from "react";

const noSubscribe = () => () => {};
// Supabase's session cookie (sb-<project>-auth-token, possibly chunked .0/.1) is readable by the page.
const hasSession = () => /(?:^|;\s*)sb-[^=]+-auth-token/.test(document.cookie);

/**
 * `signedIn` for a visitor holding a session, `signedOut` otherwise. The
 * landing page is built once for everyone, so it asks the browser; the server
 * render is the signed-out one. An expired session still reads as signed in,
 * and its "Open the app" lands on sign-in, as the app would send it.
 */
export function VisitorSwap({ signedIn, signedOut }: { signedIn: ReactNode; signedOut: ReactNode }) {
  return useSyncExternalStore(noSubscribe, hasSession, () => false) ? signedIn : signedOut;
}
