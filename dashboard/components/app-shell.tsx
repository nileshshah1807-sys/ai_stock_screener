import Link from "next/link";
import { Suspense } from "react";
import { ArrowLeftRight, Bookmark, ChartArea, LayoutGrid, LogOut, Shapes } from "lucide-react";

import { cn } from "@/lib/utils";
import { BrandMark } from "@/components/brand-mark";
import { Button } from "@/components/ui/button";
import { FreshnessBanner } from "@/components/freshness-banner";
import { HealthLink } from "@/components/health-link";
import { NotificationBell, NotificationBellFallback } from "@/components/notifications/bell";
import { ThemeToggle } from "@/components/theme-toggle";
import { NavLink } from "@/components/nav-link";
import { MarketProvider } from "@/components/market-provider";
import { MarketSwitch } from "@/components/market-switch";
import { GlassTrack } from "@/components/glass-track";
import { GlobalSearch, GlobalSearchButton } from "@/components/global-search";
import { SmoothDetails } from "@/components/motion";
import { formatDate } from "@/lib/format";
import { marketPath, type Market } from "@/lib/markets";
import { TOOLS } from "@/lib/tools";
import type { BellState } from "@/lib/notifications";
import type { ScreenerRun } from "@/lib/types";
import type { Viewer } from "@/lib/auth";

import { signOut } from "@/app/login/actions";

/*
 * Five destinations. That is also the most a phone's bottom tab bar holds; the
 * next destination needs an overflow menu, not a sixth tab.
 *
 * Run health was the sixth and now lives with the account controls
 * (HealthLink): it is about the system that produced the rankings, not a place
 * the stocks are, and notifications -- the other thing about "what changed" --
 * sit beside it there.
 *
 * Market (breadth across the whole market) is a destination of its own,
 * beside the screener. Tools is one tab for several views beside the ranking
 * -- earnings calls, results, returns -- because a tab apiece would be the
 * sixth, seventh and eighth. The tab opens the first tool and stays lit on
 * all of them; the row that picks between them is ToolsNav, in the tools
 * layout.
 *
 * Markets are deliberately NOT in this list. Which market you are looking at
 * and which view you are looking at are independent axes -- every destination
 * exists in every market -- so folding them into one row would misrepresent
 * the structure and would multiply this group's length by the market count.
 */
const TOOL_PATHS = TOOLS.map((tool) => tool.path);

const NAV: readonly { path: string; label: string; icon: typeof LayoutGrid; also?: readonly string[] }[] = [
  { path: "", label: "Screener", icon: LayoutGrid },
  { path: "/market", label: "Market", icon: ChartArea },
  { path: TOOL_PATHS[0], label: "Tools", icon: Shapes, also: TOOL_PATHS },
  { path: "/watchlists", label: "Watchlists", icon: Bookmark },
  { path: "/movers", label: "Movers", icon: ArrowLeftRight },
];

function PrimaryNav({ market, className }: { market: Market; className: string }) {
  return (
    <GlassTrack label="Primary" variant="tabs" className={className}>
      {NAV.map(({ path, label, icon: Icon, also }) => (
        <NavLink
          key={path}
          href={marketPath(market.slug, path)}
          also={also?.map((other) => marketPath(market.slug, other))}
          // The screener is the market root, so it must match exactly or
          // it reads as active on every page in the market.
          exact={path === ""}
        >
          <Icon className="size-4 shrink-0" aria-hidden />
          <span className="whitespace-nowrap">{label}</span>
        </NavLink>
      ))}
    </GlassTrack>
  );
}

function Brand({ run, market }: { run: ScreenerRun | null; market: Market }) {
  return (
    <Link
      href={marketPath(market.slug)}
      className={cn(
        "flex min-w-0 items-center gap-2.5 rounded-md",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      )}
    >
      <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
        <BrandMark className="size-4" />
      </span>
      <span className="flex min-w-0 items-baseline gap-2">
        <span className="truncate text-[0.9375rem] font-semibold tracking-[-0.02em]">
          Winnow
        </span>
        {/*
          pr-px, and it is not a fudge. This line sizes its box to its text,
          and subpixel antialiasing bleeds past that edge for `truncate`'s
          overflow:hidden to shave -- it rendered "v5.0" as "v5.C". One pixel
          of trailing room gives the last glyph somewhere to land.
        */}
        <span className="tabular hidden truncate pr-px text-xs text-muted-foreground lg:inline">
          {run ? formatDate(run.price_bar_as_of ?? run.run_date) : "no run"}
          {run?.model_version ? ` · v${run.model_version}` : ""}
        </span>
      </span>
    </Link>
  );
}

/**
 * The account's initials in a small circle. Not a control -- it is labelled
 * and titled with the address so the identity is available to a screen reader
 * and on hover, but sign-out is the button beside it rather than a menu hidden
 * behind this.
 *
 * Hidden below `sm`, where the bar is short of room: this is the one item of
 * the cluster that does nothing when pressed, and sign-out already names the
 * account in its label, so it is the one that gives way.
 */
function Avatar({ viewer }: { viewer: Viewer }) {
  const initials = viewer.email.slice(0, 2).toUpperCase();
  return (
    <span
      className="ml-1 hidden size-7 shrink-0 items-center justify-center rounded-full bg-muted text-[0.625rem] font-semibold tracking-[0.02em] text-muted-foreground ring-1 ring-border sm:flex"
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
        className="text-muted-foreground hover:text-foreground"
        aria-label={`Sign out ${viewer.email}`}
        title="Sign out"
      >
        <LogOut className="size-4" aria-hidden />
      </Button>
    </form>
  );
}

/**
 * Application chrome: a solid bar across the top of the page, then the view.
 *
 * The bar is three zones -- identity, navigation, account. Identity is the
 * brand and the market switch, which qualifies the brand the way the run date
 * beside it does: it says *which* screener this is, not where to go next.
 * Navigation is a row of text tabs whose current item is marked by an
 * underline along the bar's bottom edge; the underline slides between tabs on
 * pointer-down (GlassTrack), so a press is answered before the route is.
 *
 * Below xl the tabs wrap onto a second row of the bar rather than squeezing
 * the brand, and below md they leave the bar for a solid tab bar at the
 * bottom of the screen, in thumb reach.
 *
 * The tabs are text from md up, where the labels sit in one row and read at a
 * glance; the phone's tab bar adds an icon over each label, because five
 * small labels side by side need a shape for the thumb to find.
 *
 * Content sits on the page ground, solid, with no sheet around it. The bar is
 * sticky and opaque, with one hairline under it, so figures scrolling beneath
 * never show through the controls.
 */
export function AppShell({
  run,
  viewer,
  market,
  notifications,
  children,
}: {
  run: ScreenerRun | null;
  viewer: Viewer;
  market: Market;
  notifications: Promise<BellState>;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-dvh flex-col max-md:pb-[calc(4rem+env(safe-area-inset-bottom))]">
      <header className="sticky top-0 z-30 border-b bg-card">
        <div className="mx-auto flex w-full max-w-[1440px] flex-wrap items-center gap-x-6 px-4 sm:px-6">
          {/* min-w-0 so a long brand can truncate instead of forcing the bar
              wider than the viewport. */}
          <div className="flex h-14 min-w-0 flex-1 items-center gap-3">
            <Brand run={run} market={market} />
            <span aria-hidden className="hidden h-5 w-px shrink-0 bg-border sm:block" />
            <MarketSwitch current={market} />
          </div>

          {/*
            md to xl: `order-last w-full` drops the tabs onto their own row of
            the bar, so they never compete with the brand; the negative margin
            lines the first tab's label up with the brand's mark. From xl they
            sit between the side zones, as tall as the bar, so the underline
            lands on its bottom edge.

            shrink-0 there: the nav is the one element that must never
            compress, because its labels are the app's primary destinations.
          */}
          <PrimaryNav
            market={market}
            className={cn(
              "max-md:hidden md:order-last md:-mx-3 md:h-11 md:w-[calc(100%+1.5rem)]",
              "xl:order-none xl:mx-0 xl:h-14 xl:w-auto xl:shrink-0",
            )}
          />

          {/*
            Account. flex-1 only from xl, where the tabs sit between the two
            side zones and equal widths are what centre them. Below that the
            tabs have wrapped, and natural width gives the identity zone
            everything the icons do not need.

            Left to right: find, what changed, how the system is doing, how it
            looks, leaving, who. `key` on the bell so switching market resets
            its count to that market's rather than carrying the other's over.
          */}
          <div className="flex h-14 shrink-0 items-center justify-end gap-0.5 xl:flex-1">
            <GlobalSearchButton />
            <Suspense key={market.slug} fallback={<NotificationBellFallback />}>
              <NotificationBell market={market} state={notifications} />
            </Suspense>
            {/*
              Not on a phone: the theme toggle and run health. The theme still
              follows the phone's own setting, and run health is linked from
              the footer instead.
            */}
            <span className="hidden sm:contents">
              <HealthLink href={marketPath(market.slug, "/health")} />
              <ThemeToggle />
            </span>
            <SignOut viewer={viewer} />
            <Avatar viewer={viewer} />
          </div>
        </div>
      </header>

      <div className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col">
        <FreshnessBanner run={run} />

        {/*
          A single fade on first paint, deliberately not re-keyed per
          navigation. The screener layout exists specifically so that sorting
          and filtering do not re-render the chrome; remounting <main> on every
          navigation to replay an animation would throw that away and make the
          cheapest interaction in the app look like a full page load. Per-view
          motion belongs to the components that actually change.
        */}
        <main className="flex-1 animate-fade">
          <MarketProvider market={market} runDate={run?.run_date ?? null}>
            {children}
            {/* The header's search dialog: it reads the market, so it lives
                inside the provider, and is opened from the header by event. */}
            <GlobalSearch />
          </MarketProvider>
        </main>
        <SmoothDetails />

        <footer className="border-t px-4 py-5 text-xs text-muted-foreground sm:px-6">
          <p>
            {run?.model_validation_status ??
              "Research model; point-in-time out-of-sample validation pending."}{" "}
            Not investment advice. {market.advisor}
          </p>
          {/* Run health's way in on a phone, where the header has no room for it. */}
          <Link
            href={marketPath(market.slug, "/health")}
            className="mt-2 inline-block rounded underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:hidden"
          >
            Run health
          </Link>
        </footer>
      </div>

      {/*
        The phone's tab bar, outside the header on purpose: a fixed element
        inside the sticky header is painted wrongly by iOS Safari while
        scrolling -- all but the current tab vanished. Only one of the two
        PrimaryNavs is displayed at a time.
      */}
      <PrimaryNav
        market={market}
        className="fixed inset-x-0 bottom-0 z-40 border-t bg-card px-1 pb-[env(safe-area-inset-bottom)] md:hidden"
      />
    </div>
  );
}
