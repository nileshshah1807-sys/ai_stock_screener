"use client";

import { useEffect, useState, type ReactNode } from "react";

import { AppFrame, type ShellRun } from "@/components/app-frame";
import { TrialBanner } from "@/components/trial-banner";
import { readBellState, type BellState } from "@/lib/bell-reads";
import { localDay, MARKET_DAY_COLUMNS, marketDayFromRow, type MarketDay } from "@/lib/market-calendar.mjs";
import { marketFromSlug, type MarketCode, type MarketSlug } from "@/lib/markets";
import { shellAccess } from "@/lib/shell-access.mjs";
import { createClient } from "@/lib/supabase/client";
import type { Viewer } from "@/lib/auth";

type Ready = { viewer: Viewer; run: ShellRun | null; marketDay: MarketDay | null; bell: Promise<BellState> };

const RUN_COLUMNS = "run_date, price_bar_as_of, model_version, model_validation_status";

type Client = ReturnType<typeof createClient>;

async function claimsOf(supabase: Client) {
  const { data, error } = await supabase.auth.getClaims();
  return error ? null : (data?.claims ?? null);
}

async function readRun(supabase: Client, market: MarketCode): Promise<ShellRun | null> {
  // As getLatestRun: a reservation (row_count 0) is not a run.
  const { data } = await supabase
    .from("screener_runs_visible")
    .select(RUN_COLUMNS)
    .eq("market", market)
    .gt("row_count", 0)
    .order("run_date", { ascending: false })
    .limit(1)
    .maybeSingle();
  return (data as ShellRun | null) ?? null;
}

async function readMarketDay(supabase: Client, market: MarketCode, timeZone: string): Promise<MarketDay | null> {
  const { data } = await supabase
    .from("market_calendar")
    .select(MARKET_DAY_COLUMNS)
    .eq("market", market)
    .eq("day", localDay(Date.now(), timeZone))
    .maybeSingle();
  return marketDayFromRow(data);
}

/**
 * The signed-in chrome for a page served as a static file (the Flows page first): the
 * HTML carries no viewer and no data, so the access check, the header and the page's
 * reads all happen here, in the browser, and the Worker runs no Next render for it.
 *
 * Access is lib/shell-access.mjs, the proxy's and requireAccess()'s rule; it decides
 * only what this tab shows. What it may read is still decided where the data is: RLS
 * on every Supabase read here, and the token check in /api/objects (lib/object-gate.mjs).
 * Until the check is done the page shows `fallback`, its own skeleton.
 */
export function BrowserShell({ slug, fallback, children }: { slug: MarketSlug; fallback: ReactNode; children: ReactNode }) {
  const market = marketFromSlug(slug)!;
  const [ready, setReady] = useState<Ready | null>(null);

  useEffect(() => {
    let current = true;
    const supabase = createClient();
    (async () => {
      const path = `${window.location.pathname}${window.location.search}`;
      let decision = shellAccess(await claimsOf(supabase), path);
      if (decision.kind === "legacy") {
        // A token from before the access hook: a fresh one carries the plan claim.
        await supabase.auth.refreshSession();
        decision = shellAccess(await claimsOf(supabase), path);
        // shortcut: a token still without a plan claim is refused, not looked up in the allowlist; only if the access hook is ever removed.
        if (decision.kind === "legacy") decision = { kind: "redirect", to: "/no-access" };
      }
      if (decision.kind === "redirect") {
        if (decision.signOut) await supabase.auth.signOut({ scope: "local" }).catch(() => undefined);
        window.location.replace(decision.to);
        return;
      }
      const bell = readBellState(supabase, market.code);
      const [run, marketDay] = await Promise.all([
        readRun(supabase, market.code).catch(() => null),
        readMarketDay(supabase, market.code, market.timezone).catch(() => null),
      ]);
      if (current) setReady({ viewer: decision.viewer as Viewer, run, marketDay, bell });
    })();
    return () => {
      current = false;
    };
  }, [market.code, market.timezone]);

  if (!ready) return <>{fallback}</>;
  const { viewer, run, marketDay, bell } = ready;
  return (
    <AppFrame
      run={run}
      marketDay={marketDay}
      viewer={viewer}
      market={market}
      notifications={bell}
      // shortcut: TABLE_BACKEND is a Worker variable the static HTML cannot see; no static page reads live quotes yet.
      liveFromR2={false}
      // shortcut: no subscription read, so a trial viewer who already set up a plan sees "See the plan", not "Manage".
      trialBanner={viewer.access.kind === "trial" && viewer.access.daysLeft ? <TrialBanner days={viewer.access.daysLeft} /> : null}
    >
      {children}
    </AppFrame>
  );
}
