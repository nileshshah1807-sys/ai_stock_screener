"use client";

import { useSyncExternalStore, type ReactNode } from "react";

import { authCookieNames } from "@/lib/auth-cookies.mjs";

const noSubscribe = () => () => {};
// Supabase's session cookie is readable by the page; a sign-in's leftover code-verifier cookie is not a session.
export const hasSession = () => authCookieNames(document.cookie).length > 0;

/**
 * `signedIn` for a visitor holding a session, `signedOut` otherwise. The
 * landing page is built once for everyone, so it asks the browser; the server
 * render is the signed-out one. An expired session still reads as signed in,
 * and its "Open the app" lands on sign-in, as the app would send it.
 */
export function VisitorSwap({ signedIn, signedOut }: { signedIn: ReactNode; signedOut: ReactNode }) {
  return useSyncExternalStore(noSubscribe, hasSession, () => false) ? signedIn : signedOut;
}
