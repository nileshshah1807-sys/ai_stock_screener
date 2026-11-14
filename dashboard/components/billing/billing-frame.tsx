import type { ReactNode } from "react";
import Link from "next/link";

import { BrandMark } from "@/components/brand-mark";
import type { Session } from "@/lib/auth";
import { SiteFooter } from "@/components/site-footer";
import { LEGAL } from "@/lib/legal";
import { isEntitled } from "@/lib/billing.mjs";

const QUIET_LINK =
  "rounded text-sm text-muted-foreground underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/**
 * Pricing and Account. Both stand outside the signed-in app's chrome, because
 * both must work for someone whose plan has run out -- the app would send them
 * straight back here. The mark links into the app only when the plan allows it.
 */
export function BillingFrame({ session, children }: { session: Session | null; children: ReactNode }) {
  const inApp = session ? isEntitled(session.access) : false;

  return (
    <div className="flex min-h-screen flex-col">
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-10 sm:py-14">
        <div className="mb-8 flex items-center justify-between gap-4">
          <Link
            href={inApp ? "/screener" : "/login"}
            className="inline-flex items-center gap-2.5 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <BrandMark className="size-4" />
            </span>
            <span className="text-lead font-semibold tracking-[-0.011em]">{LEGAL.service}</span>
          </Link>
          {inApp ? (
            <Link href="/screener" className={QUIET_LINK}>
              Back to the app
            </Link>
          ) : !session ? (
            <Link href="/login" className={QUIET_LINK}>
              Sign in
            </Link>
          ) : null}
        </div>

        {children}
      </main>
      <SiteFooter />
    </div>
  );
}
