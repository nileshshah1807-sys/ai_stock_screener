import Link from "next/link";
import { Activity, ArrowLeftRight, Bookmark, LayoutGrid, LogOut } from "lucide-react";

import { cn } from "@/lib/utils";
import { BrandMark } from "@/components/brand-mark";
import { Button } from "@/components/ui/button";
import { FreshnessBanner } from "@/components/freshness-banner";
import { ThemeToggle } from "@/components/theme-toggle";
import { NavLink } from "@/components/nav-link";
import { MarketProvider } from "@/components/market-provider";
import { MarketSwitch } from "@/components/market-switch";
import { GlassTrack } from "@/components/glass-track";
import { formatDate } from "@/lib/format";
import { marketPath, type Market } from "@/lib/markets";
import type { ScreenerRun } from "@/lib/types";
import type { Viewer } from "@/lib/auth";

import { signOut } from "@/app/login/actions";

/*
 * Four destinations. The comment on AppShell notes this group stays comfortable
 * to about six before it needs an overflow menu; Watchlists is the fourth, so
 * there is room, but that ceiling is now closer than it was.
 *
 * Markets are deliberately NOT in this list. Which market you are looking at
 * and which view you are looking at are independent axes -- every destination
 * exists in every market -- so folding them into one row would misrepresent
 * the structure and would multiply this group's length by the market count,
 * blowing straight through that ceiling.
 */
const NAV = [
  { path: "", label: "Screener", icon: LayoutGrid },
  { path: "/watchlists", label: "Watchlists", icon: Bookmark },
  { path: "/movers", label: "Movers", icon: ArrowLeftRight },
  { path: "/health", label: "Run health", icon: Activity },
] as const;

function Brand({ run, market }: { run: ScreenerRun | null; market: Market }) {
  return (
    <Link
      href={marketPath(market.slug)}
      className={cn(
        "group/brand flex min-w-0 items-center gap-2.5 rounded-full",
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
          Winnow
        </span>
        {/*
          pr-px, and it is not a fudge. This line sizes the brand block, so its
          box ends up exactly as wide as its text -- measured at 102.00px in a
          102.00px box. Subpixel antialiasing then bleeds past that edge and
          `truncate`'s overflow:hidden shaves it, which rendered "v5.0" as
          "v5.C". One pixel of trailing room gives the last glyph somewhere to
          land without changing the layout.
        */}
        <span className="tabular hidden truncate pr-px font-mono text-[11px] text-muted-foreground sm:block">
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
      className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary text-[0.6875rem] font-semibold tracking-[0.02em] text-primary-foreground shadow-[inset_0_1px_0_rgb(255_255_255/0.2)]"
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
        className="rounded-full hover:bg-(--control-hover)"
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
 *
 * The header is three zones -- identity, navigation, account -- with the two
 * side zones sharing the free space equally so the nav sits on the container's
 * true centre. It was `justify-between` across four children until markets
 * arrived, at which point the nav drifted to wherever the brand and the
 * account controls left it and the market switch floated in the gap between
 * them, belonging to neither. Grouping the switch with the brand and giving
 * the side zones equal weight is what makes the row read as composed rather
 * than as four things that happen to be on the same line.
 *
 * The heights are deliberate and form a scale: the market switch and the
 * account cluster are both 40px capsules, bracketing the row at each end,
 * while the nav track is 48px because navigation is the primary control here
 * and should dominate.
 *
 * Materials follow the Liquid Glass split. Content -- every panel and the
 * grid -- sits on solid cards inside a translucent sheet; the controls float
 * above it as glass. The header is sticky, so as the page scrolls the content
 * passes *under* those capsules and softens behind a scroll-edge blur rather
 * than meeting a hard rule. On a phone the primary nav leaves the header
 * entirely and becomes a floating tab bar in thumb reach.
 */
export function AppShell({
  run,
  viewer,
  market,
  children,
}: {
  run: ScreenerRun | null;
  viewer: Viewer;
  market: Market;
  children: React.ReactNode;
}) {
  return (
    /* lg:p-8 rather than p-10. The screener grid is bounded to the viewport so
       its header can stay pinned, which makes every rem of shell chrome a rem
       the rows do not get; 8 still reads as a floating sheet. */
    /* No background here: the page ground and its ambient field are painted
       by body, and an opaque fill on this wrapper would cover them. */
    <div className="min-h-dvh p-0 sm:p-6 lg:p-8">
      <div
        className={cn(
          "workspace-sheet mx-auto flex min-h-dvh w-full max-w-[1440px] flex-col",
          // overflow-clip, not overflow-hidden. Both round the corners, but
          // `hidden` makes the sheet a scroll container, and a sticky header
          // resolves against the nearest one -- it would pin to a box that
          // never scrolls, which is the same as not pinning at all.
          "sm:min-h-0 sm:rounded-workspace sm:overflow-clip",
          // Room for the floating tab bar, so it never sits over the footer.
          "max-md:pb-24",
        )}
      >
        {/*
          Three zones: identity left, navigation centred, account right.

          The side zones are `flex-1` rather than the header being
          `justify-between`, and that is the whole fix. With space-between and
          four children the gaps are simply whatever is left over, so the nav
          sat wherever the brand and the account controls happened to leave it
          and shifted every time either changed width. Two equal side zones put
          the nav on the container's true centre and hold it there.
        */}
        <header className="scroll-edge sticky top-0 z-30 flex flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3 sm:px-8 sm:py-4">
          {/*
            Identity: what you are looking at. The market switch belongs here
            rather than out on its own, because it qualifies the brand the way
            the run date beneath it does -- it says *which* screener this is,
            not where to go next. Floating between the brand and the nav it read
            as a stray control belonging to neither.

            min-w-0 so a long brand can truncate instead of forcing the header
            wider than the sheet.
          */}
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <Brand run={run} market={market} />
            {/*
              A hairline, not a gap. Adjacency alone reads as two unrelated
              controls; the rule says the switch modifies the brand. Hidden on
              small screens, where the two already stack against the viewport
              edge and the rule would only add noise.
            */}
            <span
              aria-hidden
              className="hidden h-8 w-px shrink-0 bg-border sm:block"
            />
            <MarketSwitch current={market} />
          </div>

          {/*
            The recessed track is what the filled active pill sits in. Without
            it the pill reads as a stray button floating in the header.
            `order-last` below the breakpoint drops the group onto its own row
            so it never competes with the brand for horizontal space.

            That breakpoint is xl, not lg, and the 256px matter. The nav track
            is 540px and the two side zones are equal, so a single row needs
            roughly 540 + 2x283 + gaps before the identity zone starts losing
            room. At lg the row was technically wide enough to *fit* but not to
            fit comfortably: measured at 1100px the brand was crushed to 11px
            of its 66px, rendering as "W...". Wrapping at xl means the one-row
            layout is only used where it genuinely works.

            shrink-0 there: the nav is the one element that must never compress,
            because its labels are the app's primary destinations.
          */}
          <GlassTrack
            label="Primary"
            className={cn(
              "gap-0.5 p-1",
              // Phone: a floating tab bar, thicker glass because it rides over
              // the grid's figures rather than over the header.
              "max-md:glass-thick max-md:fixed max-md:inset-x-3 max-md:z-40",
              "max-md:bottom-[calc(0.75rem+env(safe-area-inset-bottom))]",
              "md:order-last md:w-full",
              "xl:order-none xl:w-auto xl:shrink-0",
            )}
          >
            {NAV.map(({ path, label, icon: Icon }) => (
              <NavLink
                key={path}
                href={marketPath(market.slug, path)}
                // The screener is the market root, so it must match exactly or
                // it reads as active on every page in the market.
                exact={path === ""}
              >
                <Icon className="size-4 shrink-0" aria-hidden />
                <span className="whitespace-nowrap">{label}</span>
              </NavLink>
            ))}
          </GlassTrack>

          {/*
            Account. flex-1 only from xl, where the nav actually sits between
            the two side zones and equal widths are what centre it. Below that
            the nav has wrapped to its own row, so equal zones would buy
            nothing and cost real space -- on a 430px phone they handed the
            account controls 187px to display 120px of icons while squeezing
            the brand down to "W...". Natural width plus justify-end gives the
            identity zone everything the icons do not need.
          */}
          <div className="flex shrink-0 items-center justify-end xl:flex-1">
            <div className="glass flex items-center gap-0.5 rounded-full p-0.5">
              <ThemeToggle />
              <SignOut viewer={viewer} />
              <Avatar viewer={viewer} />
            </div>
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
        <main className="flex-1 animate-fade">
          <MarketProvider market={market}>{children}</MarketProvider>
        </main>

        <footer className="border-t px-4 py-5 text-xs text-muted-foreground sm:px-8">
          <p>
            {run?.model_validation_status ??
              "Research model; point-in-time out-of-sample validation pending."}{" "}
            Not investment advice. {market.advisor}
          </p>
        </footer>
      </div>
    </div>
  );
}
