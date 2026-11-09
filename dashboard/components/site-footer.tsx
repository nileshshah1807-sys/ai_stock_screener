import Link from "next/link";
import type { ReactNode } from "react";

import { LEGAL, LEGAL_PAGES } from "@/lib/legal";
import { cn } from "@/lib/utils";

const X_URL = "https://x.com/ChirayuShah2103";
const X_LABEL = "@ChirayuShah2103 on X (opens in a new tab)";

const LINK =
  "rounded underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

const LINKS = [{ href: "/help", label: "Help & Support" }, { href: "/pricing", label: "Pricing" }, ...LEGAL_PAGES] as const;

/**
 * The one footer for every page: landing, the signed-in app, billing and the
 * legal pages. `width` sizes the inner column to the page it closes; `children`
 * is a page's own line above the disclaimer (the app's run-validation status).
 */
export function SiteFooter({ width = "max-w-3xl px-4", children }: { width?: string; children?: ReactNode }) {
  return (
    <footer className="border-t bg-card text-xs text-muted-foreground">
      <div className={cn("mx-auto w-full py-8", width)}>
        <p className="text-sm font-medium text-foreground">
          {LEGAL.service} <span className="font-normal text-muted-foreground">· Daily equity research for NSE and US stocks</span>
        </p>
        <nav aria-label="Footer" className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-sm">
          {LINKS.map((link) => (
            <Link key={link.href} href={link.href} className={LINK}>{link.label}</Link>
          ))}
          <a href={`mailto:${LEGAL.contactEmail}`} className={LINK}>{LEGAL.contactEmail}</a>
          <a href={X_URL} target="_blank" rel="me noopener" aria-label={X_LABEL} className={cn(LINK, "inline-flex items-center gap-1.5")}>
            <svg aria-hidden viewBox="0 0 24 24" className="size-4 fill-current">
              <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
            </svg>
            X
          </a>
        </nav>
        {children ? <div className="mt-4">{children}</div> : null}
        <p className="mt-4 leading-relaxed">
          Data for research and education, not investment advice. {LEGAL.service} is not a SEBI-registered investment adviser or research analyst.
          Made and run by {LEGAL.operator}, {LEGAL.operatorForm}. © {new Date().getFullYear()} {LEGAL.service}.
        </p>
      </div>
    </footer>
  );
}
