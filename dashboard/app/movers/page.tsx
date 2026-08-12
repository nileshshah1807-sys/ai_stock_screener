import Link from "next/link";
import type { Metadata } from "next";
import { ArrowDownRight, ArrowUpRight, Sparkles, TrendingDown, TrendingUp } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { RatingBadge } from "@/components/rating-badge";
import { requireAccess } from "@/lib/auth";
import { formatDate, formatScore, MISSING } from "@/lib/format";
import { getLatestRun, getMovers } from "@/lib/queries";
import type { MoverRow } from "@/lib/types";
import { cn } from "@/lib/utils";

export const metadata: Metadata = { title: "Movers" };
export const dynamic = "force-dynamic";

function RankDelta({ value }: { value: number | null }) {
  if (value === null || value === 0) {
    return <span className="text-muted-foreground">{MISSING}</span>;
  }
  const up = value > 0;
  return (
    <span
      className={cn(
        "tabular inline-flex items-center gap-0.5 font-mono text-xs",
        up ? "text-positive" : "text-negative",
      )}
    >
      {up ? (
        <ArrowUpRight className="size-3" aria-hidden />
      ) : (
        <ArrowDownRight className="size-3" aria-hidden />
      )}
      {up ? "+" : ""}
      {value}
    </span>
  );
}

function MoverList({
  title,
  description,
  icon: Icon,
  rows,
  mode,
}: {
  title: string;
  description: string;
  icon: typeof TrendingUp;
  rows: MoverRow[];
  mode: "rank" | "rating" | "new";
}) {
  return (
    <section className="rounded-lg border bg-card">
      <div className="border-b px-4 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Icon className="size-4 text-muted-foreground" aria-hidden />
          {title}
          <span className="tabular ml-auto font-mono text-xs font-normal text-muted-foreground">
            {rows.length}
          </span>
        </h2>
        <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
      </div>

      {rows.length ? (
        <ul className="divide-y">
          {rows.map((row) => (
            <li key={row.symbol}>
              <Link
                href={`/stocks/${row.symbol}`}
                className="flex items-center gap-3 px-4 py-2 hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="tabular w-8 shrink-0 font-mono text-xs text-muted-foreground">
                  {row.investment_rank ?? MISSING}
                </span>

                <span className="min-w-0 flex-1">
                  <span className="block font-mono text-xs font-semibold">
                    {row.symbol}
                  </span>
                  <span className="block truncate text-[11px] text-muted-foreground">
                    {row.company ?? MISSING}
                  </span>
                </span>

                {mode === "rank" ? (
                  <>
                    <span className="tabular hidden font-mono text-[11px] text-muted-foreground sm:inline">
                      {row.prev_investment_rank ?? MISSING} →{" "}
                      {row.investment_rank ?? MISSING}
                    </span>
                    <RankDelta value={row.rank_change} />
                  </>
                ) : null}

                {mode === "rating" ? (
                  <span className="flex items-center gap-1.5">
                    <RatingBadge rating={row.prev_rating} />
                    <span className="text-muted-foreground" aria-label="changed to">
                      →
                    </span>
                    <RatingBadge rating={row.rating} />
                  </span>
                ) : null}

                {mode === "new" ? (
                  <>
                    <span className="tabular font-mono text-xs">
                      {formatScore(row.decision_score)}
                    </span>
                    <RatingBadge rating={row.rating} />
                  </>
                ) : null}
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="px-4 py-8 text-center text-sm text-muted-foreground">
          Nothing in this bucket for this run.
        </p>
      )}
    </section>
  );
}

export default async function MoversPage() {
  const viewer = await requireAccess();
  const run = await getLatestRun();

  if (!run) {
    return (
      <AppShell run={null} viewer={viewer}>
        <div className="px-4 py-6 sm:px-6">
          <p className="text-sm text-muted-foreground">
            No screener run has been published yet.
          </p>
        </div>
      </AppShell>
    );
  }

  const movers = await getMovers(run.run_date);

  const hasComparison = Boolean(movers.previousOn);

  return (
    <AppShell run={run} viewer={viewer}>
      <div className="space-y-4 px-4 py-5 sm:px-6">
        <div>
          <h1 className="text-lg font-semibold">Movers</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {hasComparison ? (
              <>
                {formatDate(run.run_date)} compared with the previous published
                run, {formatDate(movers.previousOn)}.
              </>
            ) : (
              <>
                Only one run is on record. Movement appears once a second run
                has been published.
              </>
            )}
          </p>
        </div>

        {/* The comparison is against the previous *available* run, not
            yesterday's calendar date, so a weekend or exchange holiday does not
            register as the whole universe entering for the first time. */}
        {hasComparison ? (
          <div className="grid gap-4 lg:grid-cols-2">
            <MoverList
              title="Biggest rank gains"
              description="Largest improvements in Investment Rank since the previous run."
              icon={TrendingUp}
              rows={movers.climbers}
              mode="rank"
            />
            <MoverList
              title="Biggest rank falls"
              description="Largest deteriorations in Investment Rank since the previous run."
              icon={TrendingDown}
              rows={movers.fallers}
              mode="rank"
            />
            <MoverList
              title="Rating upgrades"
              description="Published rating moved up a class."
              icon={ArrowUpRight}
              rows={movers.upgrades}
              mode="rating"
            />
            <MoverList
              title="Rating downgrades"
              description="Published rating moved down a class."
              icon={ArrowDownRight}
              rows={movers.downgrades}
              mode="rating"
            />
            <MoverList
              title="New to the universe"
              description="Scored for the first time in the recorded history."
              icon={Sparkles}
              rows={movers.entrants}
              mode="new"
            />
          </div>
        ) : null}

        <p className="pt-2 text-xs leading-relaxed text-muted-foreground">
          A rating change reflects a change in evidence or in which policy
          ceiling applies. It is not a trade signal, and the underlying model
          has not been validated out of sample.
        </p>
      </div>
    </AppShell>
  );
}
