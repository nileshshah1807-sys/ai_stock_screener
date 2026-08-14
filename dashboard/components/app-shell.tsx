import Link from "next/link";
import { Activity, ArrowLeftRight, LayoutGrid, LogOut, Terminal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FreshnessBanner } from "@/components/freshness-banner";
import { ThemeToggle } from "@/components/theme-toggle";
import { NavLink } from "@/components/nav-link";
import { formatDate } from "@/lib/format";
import type { ScreenerRun } from "@/lib/types";
import type { Viewer } from "@/lib/auth";

import { signOut } from "@/app/login/actions";

const NAV = [
  { href: "/", label: "Screener", icon: LayoutGrid },
  { href: "/movers", label: "Movers", icon: ArrowLeftRight },
  { href: "/health", label: "Run health", icon: Activity },
] as const;

const RAIL_WIDTH = "15rem"; /* 240px */

function Brand({ run, compact = false }: { run: ScreenerRun | null; compact?: boolean }) {
  return (
    <Link
      href="/"
      className="flex items-center gap-2.5 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="flex size-8 shrink-0 items-center justify-center rounded bg-primary text-primary-foreground">
        <Terminal className="size-4" aria-hidden />
      </span>
      <span className="min-w-0">
        <span className="block truncate text-sm font-semibold tracking-tight">
          NSE Screener
        </span>
        {!compact ? (
          <span className="tabular block truncate font-mono text-[11px] text-muted-foreground">
            {run ? formatDate(run.price_bar_as_of ?? run.run_date) : "no run"}
            {run?.model_version ? ` · v${run.model_version}` : ""}
          </span>
        ) : null}
      </span>
    </Link>
  );
}

function SignOut({ viewer }: { viewer: Viewer }) {
  return (
    <form action={signOut}>
      <Button
        type="submit"
        variant="ghost"
        size="icon"
        aria-label={`Sign out ${viewer.email}`}
        title={viewer.email}
      >
        <LogOut className="size-4" aria-hidden />
      </Button>
    </form>
  );
}

/**
 * Application chrome: a fixed rail on desktop, a stacked top bar on small
 * screens.
 *
 * The rail is the darkest surface so the content column reads as lifted off
 * it. Nav items carry an icon *and* a label at every breakpoint -- an icon-only
 * rail saves 150px and costs discoverability, which is the wrong trade for a
 * tool people use occasionally.
 */
export function AppShell({
  run,
  viewer,
  children,
}: {
  run: ScreenerRun | null;
  viewer: Viewer;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-dvh">
      <aside
        style={{ width: RAIL_WIDTH }}
        className="fixed inset-y-0 left-0 z-40 hidden flex-col border-r border-sidebar-border bg-sidebar p-3 lg:flex"
      >
        <div className="px-1 py-2">
          <Brand run={run} />
        </div>

        <nav aria-label="Primary" className="mt-6 flex flex-col gap-1">
          {NAV.map(({ href, label, icon: Icon }) => (
            <NavLink key={href} href={href} rail>
              <Icon className="size-4 shrink-0" aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto flex items-center justify-between border-t border-sidebar-border pt-3">
          <span className="truncate px-1 text-[11px] text-muted-foreground" title={viewer.email}>
            {viewer.email}
          </span>
          <div className="flex shrink-0 items-center">
            <ThemeToggle />
            <SignOut viewer={viewer} />
          </div>
        </div>
      </aside>

      <div className="flex min-h-dvh flex-col lg:pl-[15rem]">
        <header className="sticky top-0 z-30 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80 lg:hidden">
          <div className="flex h-14 items-center gap-3 px-4">
            <Brand run={run} compact />
            <div className="ml-auto flex items-center">
              <ThemeToggle />
              <SignOut viewer={viewer} />
            </div>
          </div>

          <nav
            aria-label="Primary"
            className="flex gap-1 overflow-x-auto px-3 pb-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          >
            {NAV.map(({ href, label, icon: Icon }) => (
              <NavLink key={href} href={href}>
                <Icon className="size-4 shrink-0" aria-hidden />
                <span className="whitespace-nowrap">{label}</span>
              </NavLink>
            ))}
          </nav>
        </header>

        <FreshnessBanner run={run} />

        <main className="flex-1">{children}</main>

        <footer className="border-t px-4 py-4 text-xs text-muted-foreground sm:px-6">
          <p>
            {run?.model_validation_status ??
              "Research model; point-in-time out-of-sample validation pending."}{" "}
            Not investment advice. Consult a SEBI-registered advisor.
          </p>
        </footer>
      </div>
    </div>
  );
}
