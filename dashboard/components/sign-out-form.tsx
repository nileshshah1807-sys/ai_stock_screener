"use client";

import type { FormEvent, ReactNode } from "react";

import { authCookieNames, expireCookie } from "@/lib/auth-cookies.mjs";
import { lazyClient } from "@/lib/supabase/lazy-client";

/**
 * Signs out in the browser: Supabase is called directly and the session cookies are cleared here.
 * A server action would re-render the current page in the same request (60-600 ms of Worker CPU
 * against the Free plan's 10 ms), so signing out itself hit 1102 (14 Nov 2026).
 */
export function SignOutForm({ className, children }: { className?: string; children: ReactNode }) {
  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const expireSession = () => authCookieNames(document.cookie).forEach((name) => (document.cookie = expireCookie(name)));
    try {
      // signOut() keeps the session when it cannot load it first (a refresh that fails), and can
      // wait on the auth lock; either way the browser signs itself out by expiring the cookies.
      const result = await Promise.race([
        (await lazyClient()).auth.signOut(),
        new Promise<{ error: Error }>((resolve) => setTimeout(() => resolve({ error: new Error("timeout") }), 3000)),
      ]);
      if (result.error) expireSession();
    } catch {
      expireSession();
    } finally {
      // A full load, not router.push: the client router cache still holds signed-in pages.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/login");
    }
  }
  return (
    <form onSubmit={onSubmit} className={className}>
      {children}
    </form>
  );
}
