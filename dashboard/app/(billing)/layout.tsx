import Link from "next/link";

import { BrandMark } from "@/components/brand-mark";
import { getSession } from "@/lib/auth";
import { LEGAL, LEGAL_PAGES } from "@/lib/legal";
import { hasAccess } from "@/lib/billing.mjs";

const QUIET_LINK =
  "rounded text-sm text-muted-foreground underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/**
 * Pricing and Account. Both stand outside the signed-in app's chrome, because
 * both must work for someone whose plan has run out -- the app would send them
 * straight back here. The mark links into the app only when the plan allows it.
 */
export default async function BillingLayout({ children }: LayoutProps<"/">) {
  const session = await getSession();
  const inApp = session ? hasAccess(session.access) : false;

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-10 sm:py-14">
      <div className="mb-8 flex items-center justify-between gap-4">
        <Link
          href={inApp ? "/" : "/login"}
          className="inline-flex items-center gap-2.5 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <BrandMark className="size-4" />
          </span>
          <span className="text-lead font-semibold tracking-[-0.011em]">{LEGAL.service}</span>
        </Link>
        {inApp ? (
          <Link href="/" className={QUIET_LINK}>
            Back to the app
          </Link>
        ) : !session ? (
          <Link href="/login" className={QUIET_LINK}>
            Sign in
          </Link>
        ) : null}
      </div>

      {children}

      <p className="mt-12 text-xs leading-relaxed text-muted-foreground">
        Research model output, not investment advice. {LEGAL.service} is not a SEBI-registered
        investment adviser or research analyst.
      </p>
      <nav aria-label="Legal" className="mt-3 flex flex-wrap gap-x-5 gap-y-2 border-t pt-5 text-xs text-muted-foreground">
        {LEGAL_PAGES.map((page) => (
          <Link key={page.href} href={page.href} className="hover:text-foreground hover:underline">
            {page.label}
          </Link>
        ))}
      </nav>
    </main>
  );
}
