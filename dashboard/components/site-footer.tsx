import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { useId, type ReactNode } from "react";

import { LEGAL, LEGAL_PAGES } from "@/lib/legal";
import { cn } from "@/lib/utils";

const X_URL = "https://x.com/ChirayuShah2103";

const LINK =
  "inline-block rounded-sm py-1.5 underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card";

/**
 * A link that leaves the site: new tab, announced as such. The arrow is tied to the
 * last word, so a label that wraps in a narrow column never strands it on its own line.
 */
function ExternalLink({ href, rel = "noopener", children }: { href: string; rel?: string; children: string }) {
  const words = children.split(" ");
  const last = words.pop();
  return (
    <a href={href} target="_blank" rel={rel} className={LINK}>
      {words.length ? `${words.join(" ")} ` : null}
      <span className="whitespace-nowrap">
        {last}
        <ArrowUpRight aria-hidden className="ml-1 inline size-3.5 align-[-0.125em]" />
      </span>
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

/** A column of links. Its title names the list; it is not a heading, so it stays out of the page's outline. */
function Group({ title, className, children }: { title: string; className?: string; children: ReactNode }) {
  const id = useId();
  return (
    <div className={className}>
      <p id={id} className="text-sm font-medium text-foreground">{title}</p>
      <ul aria-labelledby={id} className="mt-1.5 grid text-sm">{children}</ul>
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
        <nav aria-label="Footer" className="grid grid-cols-2 gap-x-6 gap-y-8 sm:grid-cols-[1.1fr_9.5rem_1fr_1fr]">
          <div className="col-span-2 sm:col-span-1">
            <p className="text-sm font-semibold text-foreground">{LEGAL.service}</p>
            <p className="mt-1 max-w-xs text-sm">Daily equity research for NSE and US stocks.</p>
          </div>
          <Group title="Support" className="col-start-1 sm:col-start-auto">
            <li><Link href="/help" className={LINK}>Help &amp; Support</Link></li>
            <li>
              <ExternalLink href={LEGAL.requestsUrl}>View my requests</ExternalLink>
            </li>
            <li><a href={`mailto:${LEGAL.contactEmail}`} className={cn(LINK, "[overflow-wrap:anywhere]")}>{LEGAL.contactEmail}</a></li>
          </Group>
          <Group title="Product" className="col-start-1 sm:col-start-auto">
            <li><Link href="/pricing" className={LINK}>Pricing</Link></li>
            <li>
              <ExternalLink href={X_URL} rel="me noopener">X</ExternalLink>
            </li>
          </Group>
          <Group title="Legal" className="col-start-2 row-span-2 row-start-2 sm:col-start-auto sm:row-span-1 sm:row-start-auto">
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
