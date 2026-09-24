import type { Metadata } from "next";

import { MarketDashboard } from "@/components/market/market-dashboard";
import type { GroupKey } from "@/components/market/group-picker";
import { formatDate } from "@/lib/format";
import { marketFromSlug } from "@/lib/markets";
import { getMarketBreadth } from "@/lib/queries";

export const metadata: Metadata = { title: "Market" };
export const dynamic = "force-dynamic";

function selectedGroup(query: Record<string, string | string[] | undefined>): GroupKey {
  const first = (value: string | string[] | undefined) =>
    (Array.isArray(value) ? value[0] : value)?.trim() || "";
  const industry = first(query.industry);
  if (industry) return { scope: "industry", name: industry };
  const sector = first(query.sector);
  if (sector) return { scope: "sector", name: sector };
  return { scope: "market", name: "" };
}

/**
 * Market breadth: how many stocks are taking part in a move, not just where
 * the index is.
 *
 * An index can rise on a handful of large names while most stocks fall; the
 * share above their averages, in Stage 2, or at new highs is what says whether
 * a trend is broad. Every series is rebuilt daily by
 * tools/publish_market_breadth.py from the same closes the model scores on.
 */
export default async function MarketPage({ params, searchParams }: PageProps<"/[market]/market">) {
  const market = marketFromSlug((await params).market)!;
  const selected = selectedGroup(await searchParams);
  const { groups, group, indices } = await getMarketBreadth(market.code, selected);
  const universe = groups.find((entry) => entry.scope === "market")?.members ?? null;

  return (
    <div className="space-y-6 px-4 py-5 sm:px-6">
      <div>
        <h1 className="text-title font-semibold">Market</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          How broadly {market.label} stocks are participating
          {universe ? ` — ${universe.toLocaleString(market.locale)} stocks the screener rates` : ""},
          session by session. Hover or drag across any chart to read every chart on that day.
        </p>
      </div>

      <MarketDashboard
        // Remount per group so a new row starts from a clean scrub.
        key={`${selected.scope}:${selected.name}`}
        market={market}
        groups={groups}
        group={group}
        indices={indices}
        selected={selected}
      />

      {group ? (
        <p className="max-w-3xl border-t pt-4 text-xs leading-relaxed text-muted-foreground">
          Updated through {formatDate(group.last_session)}. Each day counts only the stocks that
          traded that day, and each measure only the stocks with enough history for it — a stock
          listed four months ago counts toward the 50-day EMA but not the 200-day. Highs and lows
          use closing prices. Stage and RS rating use the screener&rsquo;s own rules, replayed
          over each stock&rsquo;s history. History covers today&rsquo;s universe, so stocks that
          have since delisted are not in earlier counts.
        </p>
      ) : null}
    </div>
  );
}
