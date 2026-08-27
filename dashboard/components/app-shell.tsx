import Link from "next/link";
import { Activity, ArrowLeftRight, Bookmark, LayoutGrid, LogOut } from "lucide-react";

import { cn } from "@/lib/utils";
import { BrandMark } from "@/components/brand-mark";
import { Button } from "@/components/ui/button";
import { FreshnessBanner } from "@/components/freshness-banner";
import { ThemeToggle } from "@/components/theme-toggle";
import { NavLink } from "@/components/nav-link";
import { formatDate } from "@/lib/format";
import type { ScreenerRun } from "@/lib/types";
import type { Viewer } from "@/lib/auth";

import { signOut } from "@/app/login/actions";

/*
 * Four destinations. The comment on AppShell notes this group stays comfortable
 * to about six before it needs an overflow menu; Watchlists is the fourth, so
 * there is room, but that ceiling is now closer than it was.
 */
const NAV = [
  { href: "/", label: "Screener", icon: LayoutGrid },
  { href: "/watchlists", label: "Watchlists", icon: Bookmark },
  { href: "/movers", label: "Movers", icon: ArrowLeftRight },
  { href: "/health", label: "Run health", icon: Activity },
] as const;

function Brand({ run }: { run: ScreenerRun | null }) {
  return (
    <Link
      href="/"
      className={cn(
        "group/brand flex shrink-0 items-center gap-2.5 rounded-full",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      )}
    >
      <span
        className={cn(
          "flex size-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground",
          "transition-transform duration-(--duration-slow) ease-(--ease-spring)",
          // The mark is a gauge; rotating it would read as the needle moving,
          // which is meaningless here. A straight lift keeps it legible.
          "group-hover/brand:scale-110",
        )}
      >
        <BrandMark className="size-5" />
      </span>
      <span className="min-w-0">
        <span className="block truncate text-lead font-semibold tracking-[-0.011em]">
          NSE Screener
        </span>
        <span className="tabular hidden truncate font-mono text-[11px] text-muted-foreground sm:block">
          {run ? formatDate(run.price_bar_as_of ?? run.run_date) : "no run"}
          {run?.model_version ? ` · v${run.model_version}` : ""}
        </span>
      </span>
    </Link>
  );
}

/**
 * The mock's avatar: a filled black circle with the account's initials. Not a
 * control -- it is labelled and titled with the address so the identity is
 * available to a screen reader and on hover, but sign-out is the button beside
 * it rather than a menu hidden behind this.
 */
function Avatar({ viewer }: { viewer: Viewer }) {
  const initials = viewer.email.slice(0, 2).toUpperCase();
  return (
    <span
      className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground"
      title={viewer.email}
      aria-label={`Signed in as ${viewer.email}`}
    >
      {initials}
    </span>
  );
}

function SignOut({ viewer }: { viewer: Viewer }) {
  return (
    <form action={signOut}>
      <Button
        type="submit"
        variant="ghost"
        size="icon"
        className="rounded-full"
        aria-label={`Sign out ${viewer.email}`}
        title="Sign out"
      >
        <LogOut className="size-4" aria-hidden />
      </Button>
    </form>
  );
}

/**
 * Application chrome, ported from the Figma frames (nodes 1:1049 / 1:845).
 *
 * The mock's defining structure is a single white workspace sheet floating on
 * a grey ground: 40px radius, a soft two-layer drop shadow, capped at 1440px
 * and centred. Navigation is a horizontal pill group in the sheet's header
 * rather than a side rail, with the active item filled solid black.
 *
 * This replaces the previous fixed 240px rail. The trade is deliberate and
 * worth naming: the rail could hold an arbitrary number of destinations and a
 * horizontal group cannot, so this layout is only correct while the app has a
 * handful of top-level views. At three it is comfortable; past about six the
 * group will need an overflow menu or the rail will need to come back.
 *
 * Nav items keep both icon and label at every breakpoint. The mock is
 * label-only, but an icon-free pill group gives the eye nothing to lock onto
 * when scanning back to a destination, and the icons cost 20px each.
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
    /* lg:p-8 rather than p-10. The screener grid is bounded to the viewport so
       its header can stay pinned, which makes every rem of shell chrome a rem
       the rows do not get; 8 still reads as a floating sheet. */
    <div className="min-h-dvh bg-background p-0 sm:p-6 lg:p-8">
      <div
        className={cn(
          "mx-auto flex min-h-dvh w-full max-w-[1440px] flex-col bg-workspace",
          "sm:min-h-0 sm:rounded-workspace sm:elevate-workspace sm:overflow-hidden",
        )}
      >
        <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 px-4 py-4 sm:px-8 sm:py-5">
          <Brand run={run} />

          {/*
            The recessed track is what the filled active pill sits in. Without
            it the pill reads as a stray button floating in the header.
            `order-last` on small screens drops the group onto its own row so
            it never competes with the brand for horizontal space.
          */}
          <nav
            aria-label="Primary"
            className={cn(
              "order-last flex w-full gap-1 overflow-x-auto rounded-full border bg-muted p-1.5",
              "[scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
              "lg:order-none lg:w-auto lg:overflow-visible",
            )}
          >
            {NAV.map(({ href, label, icon: Icon }) => (
              <NavLink key={href} href={href}>
                <Icon className="size-4 shrink-0" aria-hidden />
                <span className="whitespace-nowrap">{label}</span>
              </NavLink>
            ))}
          </nav>

          <div className="flex shrink-0 items-center gap-1">
            <ThemeToggle />
            <SignOut viewer={viewer} />
            <Avatar viewer={viewer} />
          </div>
        </header>

        <FreshnessBanner run={run} />

        {/*
          A single fade on first paint, deliberately not re-keyed per
          navigation. The screener layout exists specifically so that sorting
          and filtering do not re-render the chrome; remounting <main> on every
          navigation to replay an animation would throw that away and make the
          cheapest interaction in the app look like a full page load. Per-view
          motion belongs to the components that actually change.
        */}
        <main className="flex-1 animate-fade">{children}</main>

        <footer className="border-t px-4 py-5 text-xs text-muted-foreground sm:px-8">
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
