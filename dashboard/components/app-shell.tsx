import Link from "next/link";
import { Activity, ArrowLeftRight, LayoutGrid, LogOut } from "lucide-react";

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
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-40 border-b bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80">
        <div className="flex h-14 items-center gap-4 px-4 sm:px-6">
          <Link href="/" className="flex items-baseline gap-2">
            <span className="font-mono text-sm font-semibold tracking-tight">
              NSE Screener
            </span>
            {run ? (
              <span className="tabular hidden text-xs text-muted-foreground sm:inline">
                {formatDate(run.price_bar_as_of ?? run.run_date)}
              </span>
            ) : null}
          </Link>

          <nav aria-label="Primary" className="flex items-center gap-0.5">
            {NAV.map(({ href, label, icon: Icon }) => (
              <NavLink key={href} href={href}>
                <Icon className="size-3.5" aria-hidden />
                <span className="hidden sm:inline">{label}</span>
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-1">
            {run?.model_version ? (
              <span className="tabular mr-2 hidden font-mono text-[11px] text-muted-foreground lg:inline">
                model {run.model_version}
              </span>
            ) : null}
            <ThemeToggle />
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
          </div>
        </div>
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
  );
}
