import Link from "next/link";
import type { ReactNode } from "react";

import { LEGAL, LEGAL_PAGES } from "@/lib/legal";
import { cn } from "@/lib/utils";

const X_URL = "https://x.com/ChirayuShah2103";

const LINK =
  "inline-flex items-center gap-1.5 rounded-sm py-1 underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card";

/** A link that leaves the site: new tab, announced as such. */
function ExternalLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener" className={LINK}>
      {children}
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h2 className="text-xs font-semibold uppercase tracking-wide text-foreground">{title}</h2>
      <ul className="mt-2 grid gap-0.5 text-sm">{children}</ul>
    </div>
  );
}

/**
 * The one footer for every page: landing, the signed-in app, billing and the
 * legal pages. `width` sizes the inner column to the page it closes; `children`
 * is a page's own line above the disclaimer (the app's run-validation status).
 */
export function SiteFooter({ width = "max-w-3xl px-4", children }: { width?: string; children?: ReactNode }) {
  return (
    <footer className="border-t bg-card text-xs text-muted-foreground">
      <div className={cn("mx-auto w-full py-8", width)}>
        <nav aria-label="Footer" className="grid grid-cols-2 gap-x-6 gap-y-8 sm:grid-cols-[1.4fr_1fr_1fr_1fr]">
          <div className="col-span-2 sm:col-span-1">
            <p className="text-sm font-semibold text-foreground">{LEGAL.service}</p>
            <p className="mt-1 max-w-xs text-sm">Daily equity research for NSE and US stocks.</p>
          </div>
          <Group title="Product">
            <li><Link href="/pricing" className={LINK}>Pricing</Link></li>
            <li>
              <ExternalLink href={X_URL}>
                X<span aria-hidden>↗</span>
              </ExternalLink>
            </li>
          </Group>
          <Group title="Support">
            <li><Link href="/help" className={LINK}>Help &amp; Support</Link></li>
            <li>
              <ExternalLink href={LEGAL.requestsUrl}>
                View my requests<span aria-hidden>↗</span>
              </ExternalLink>
            </li>
            <li><a href={`mailto:${LEGAL.contactEmail}`} className={cn(LINK, "break-all")}>{LEGAL.contactEmail}</a></li>
          </Group>
          <Group title="Legal">
            {LEGAL_PAGES.map((link) => (
              <li key={link.href}><Link href={link.href} className={LINK}>{link.label}</Link></li>
            ))}
          </Group>
        </nav>
        {children ? <div className="mt-6">{children}</div> : null}
        <p className="mt-8 border-t pt-4 leading-relaxed">
          Data for research and education, not investment advice. {LEGAL.service} is not a SEBI-registered investment adviser or research analyst.
          Made and run by {LEGAL.operator}, {LEGAL.operatorForm}. © {new Date().getFullYear()} {LEGAL.service}.
        </p>
      </div>
    </footer>
  );
}
