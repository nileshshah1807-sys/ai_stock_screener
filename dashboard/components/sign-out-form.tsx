"use client";

import type { FormEvent, ReactNode } from "react";

import { lazyClient } from "@/lib/supabase/lazy-client";

/**
 * Signs out in the browser: Supabase is called directly and the session cookies are cleared here.
 * A server action would re-render the current page in the same request (60-600 ms of Worker CPU
 * against the Free plan's 10 ms), so signing out itself hit 1102 (14 Nov 2026).
 */
export function SignOutForm({ className, children }: { className?: string; children: ReactNode }) {
  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await (await lazyClient()).auth.signOut();
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
