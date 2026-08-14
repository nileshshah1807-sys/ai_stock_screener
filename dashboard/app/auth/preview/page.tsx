import { notFound } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { RatingBadge } from "@/components/rating-badge";
import { SummaryTiles } from "@/components/summary-tiles";
import { ScreenerTable } from "@/components/screener/screener-table";
import { DecisionScore } from "@/components/stock/decision-score";
import { FieldList, Panel } from "@/components/stock/field-list";
import { ScoreWaterfall } from "@/components/stock/score-waterfall";
import { PayloadExplorer } from "@/components/stock/payload-explorer";
import { ThemeToggle } from "@/components/theme-toggle";
import { RATINGS } from "@/lib/types";

import { previewDetailRow, previewRows, previewRun } from "./fixtures";

/**
 * Development-only design preview.
 *
 * The application is gated behind Supabase auth, so there is no way to see the
 * real surfaces without a live session and a published run. This route renders
 * the same components against fixture data so the design work can be checked
 * in a browser.
 *
 * It lives under /auth because proxy.ts already treats that prefix as public,
 * which means adding it required no change to the authentication boundary. The
 * notFound() below is the actual guard: NODE_ENV is inlined at build time, so
 * in a production build this file compiles to a route that always 404s.
 */
export const dynamic = "force-static";

export default function PreviewPage() {
  if (process.env.NODE_ENV !== "development") notFound();

  return (
    // Wrapped in the real AppShell so the rail, the pill nav, the brand mark,
    // the freshness banner and the footer are all exercised too -- those are
    // the surfaces a component-only preview would silently skip.
    <AppShell
      run={previewRun}
      viewer={{ id: "preview", email: "preview@localhost", role: "viewer" }}
    >
      <div className="flex flex-col gap-8 px-4 py-8 sm:px-8">
        <header className="flex items-center justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-wider text-muted-foreground">
              Development preview
            </p>
            <h1 className="text-title">Design system check</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Fixture data. Toggle the theme to verify both palettes.
            </p>
          </div>
          <ThemeToggle />
        </header>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Type scale</h2>
          <div className="panel flex flex-col gap-4 p-6">
            <p className="numeral text-display">1,847</p>
            <p className="text-title">Market research overview</p>
            <p className="text-heading">Score Distribution</p>
            <p className="text-lead">Evidence summary lead paragraph</p>
            <p className="text-sm">
              Body copy at 14px, the working size across the interface.
            </p>
            <p className="text-xs text-muted-foreground">
              Small label at 12px for axes and metadata.
            </p>
            <p className="text-micro uppercase tracking-wider text-muted-foreground">
              Micro chip label at 10px
            </p>
            <p className="tabular font-mono text-sm">
              0123456789 · mono tabular figures for the grid
            </p>
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Rating ramp</h2>
          <div className="panel flex flex-wrap items-center gap-3 p-6">
            {RATINGS.map((rating) => (
              <RatingBadge key={rating} rating={rating} size="md" />
            ))}
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">KPI band</h2>
          <SummaryTiles run={previewRun} />
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Screener grid</h2>
          <ScreenerTable
            rows={previewRows}
            params={new URLSearchParams()}
            sort="investment_rank"
            dir="asc"
          />
        </section>

        <section className="grid gap-4 lg:grid-cols-2">
          <Panel
            title="Decision score"
            description="The published score against the 0-100 range it is rated on. Ticks mark the REDUCE / HOLD / BUY / STRONG BUY boundaries."
          >
            <DecisionScore
              score={previewDetailRow.decision_score}
              rating={previewDetailRow.rating}
            />
          </Panel>

          <Panel
            title="Price and size"
            description="Field list inside the panel treatment."
          >
            <FieldList
              columns={2}
              fields={[
                { label: "Price", value: "₹391.15" },
                { label: "Market cap", value: "₹1,452 Cr" },
                { label: "1M", value: "+4.2%", tone: "positive" },
                { label: "3M", value: "-1.8%", tone: "negative" },
                { label: "Coverage", value: "92%", tone: "caution" },
                { label: "Liquidity", value: "A", tone: "muted" },
              ]}
            />
          </Panel>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Score waterfall</h2>
          <Panel title="How this score was produced">
            <ScoreWaterfall row={previewDetailRow} />
          </Panel>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Complete source record</h2>
          <Panel
            title="Complete source record"
            description="Must have no horizontal scrollbar, and figures must carry separators."
          >
            <PayloadExplorer payload={previewDetailRow.payload} />
          </Panel>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Every rating, as a ring</h2>
          <div className="grid gap-4 sm:grid-cols-3 xl:grid-cols-5">
            {[
              { score: 78.4, rating: "STRONG BUY" },
              { score: 68.5, rating: "BUY" },
              { score: 56.1, rating: "HOLD" },
              { score: 44.2, rating: "REDUCE" },
              { score: 31.7, rating: "SELL" },
            ].map((item) => (
              <div key={item.rating} className="panel p-5">
                <DecisionScore
                  score={item.score}
                  rating={item.rating}
                  caption={item.rating}
                />
              </div>
            ))}
          </div>
        </section>
      </div>
    </AppShell>
  );
}
