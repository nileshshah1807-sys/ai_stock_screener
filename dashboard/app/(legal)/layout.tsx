import Link from "next/link";

import { BrandMark } from "@/components/brand-mark";
import { LEGAL, LEGAL_PAGES } from "@/lib/legal";

/**
 * Terms, Privacy and Disclaimer: public pages, readable without signing in
 * (proxy.ts lets them through), because a visitor must be able to read them
 * before agreeing to them.
 *
 * The prose styles live here rather than in each page, so the three read as one
 * document set.
 */
export default function LegalLayout({ children }: LayoutProps<"/">) {
  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-10 sm:py-14">
      <Link
        href="/"
        className="mb-8 inline-flex items-center gap-2.5 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <BrandMark className="size-4" />
        </span>
        <span className="text-lead font-semibold tracking-[-0.011em]">{LEGAL.service}</span>
      </Link>

      <article className="text-sm leading-relaxed text-foreground [&_a]:underline [&_a]:underline-offset-2 [&_h1]:text-heading [&_h1]:font-semibold [&_h2]:mt-8 [&_h2]:text-base [&_h2]:font-semibold [&_li]:mt-1 [&_p]:mt-3 [&_ul]:mt-3 [&_ul]:list-disc [&_ul]:pl-5">
        {children}
      </article>

      <nav
        aria-label="Legal"
        className="mt-12 flex flex-wrap gap-x-5 gap-y-2 border-t pt-5 text-xs text-muted-foreground"
      >
        {LEGAL_PAGES.map((page) => (
          <Link key={page.href} href={page.href} className="hover:text-foreground hover:underline">
            {page.label}
          </Link>
        ))}
      </nav>
    </main>
  );
}
