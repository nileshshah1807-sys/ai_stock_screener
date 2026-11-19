import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ChevronRight, FileText } from "lucide-react";

import { AllotmentOdds } from "@/components/ipos/allotment-odds";
import { LiveDot, changeTone, priceBand, shortDate } from "@/components/ipos/ipo-row";
import { StockIdentity } from "@/components/stock-identity";
import { FieldList, Panel, type Field } from "@/components/stock/field-list";
import {
  MISSING,
  formatDate,
  formatDateTimeIST,
  formatInteger,
  formatMoney,
  formatMoneyCompact,
  formatNumber,
} from "@/lib/format";
import { getIpos, getPricesNow, getRiskFactors, type Ipo, type RiskFactor } from "@/lib/ipos";
import {
  STATUS_LABEL,
  bookSize,
  categoryTimes,
  changeFromIssue,
  formatSignedPercent,
  formatTimes,
  impliedListing,
  issueStatus,
  minInvestment,
  periodLabel,
  splitRisks,
} from "@/lib/ipos.mjs";
import { marketFromSlug, marketPath, type Market } from "@/lib/markets";
import { decodeSymbolParam } from "@/lib/symbol.mjs";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

/** NSE's names for the book's categories, in words a reader knows. */
const CATEGORY_NAMES: Record<string, string> = {
  QIB: "Qualified institutions (QIB)",
  NII: "Non-institutional (NII)",
  bNII: "Bids above ₹10 lakh",
  sNII: "Bids of ₹2–10 lakh",
  Retail: "Retail",
  Employee: "Employees",
  Shareholder: "Shareholders",
  Policyholder: "Policyholders",
};
/** The two halves of NII, set in under it. */
const NII_PARTS = new Set(["bNII", "sNII"]);

async function findIssue(slug: string, raw: string) {
  const market = marketFromSlug(slug);
  const symbol = decodeSymbolParam(raw);
  if (!market || !symbol) return null;
  const row = (await getIpos(market.code))?.find((issue) => issue.symbol === symbol) ?? null;
  return row ? { market, row } : null;
}

export async function generateMetadata({ params }: PageProps<"/[market]/ipos/[symbol]">) {
  const { market, symbol } = await params;
  const found = await findIssue(market, symbol);
  return { title: found ? `${found.row.company ?? found.row.symbol} IPO` : "IPO" };
}

/** A price with its change from the issue price beside it. */
function PriceAgainstIssue({ row, price, market }: { row: Ipo; price: number | null; market: Market }) {
  const change = changeFromIssue(row, price);
  return (
    <>
      {formatMoney(price, market, 2)}
      <span className={cn("ml-1.5", changeTone(change))}>{formatSignedPercent(change) ?? ""}</span>
    </>
  );
}

function BookTable({ row, market }: { row: Ipo; market: Market }) {
  const cell = "tabular whitespace-nowrap px-3 py-2 text-right font-mono text-[13px]";
  return (
    <div className="-mx-1 overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">Subscription by investor category, combined NSE and BSE book</caption>
        <thead>
          <tr className="whitespace-nowrap border-b text-[11px] text-muted-foreground">
            <th scope="col" className="px-3 py-2 text-left font-medium">Category</th>
            <th scope="col" className="hidden px-3 py-2 text-right font-medium sm:table-cell">Shares reserved</th>
            <th scope="col" className="hidden px-3 py-2 text-right font-medium sm:table-cell">Shares bid</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Subscribed</th>
          </tr>
        </thead>
        <tbody>
          {(row.subscription ?? []).map((entry) => (
            <tr key={entry.category} className="border-b">
              <th
                scope="row"
                className={cn(
                  "px-3 py-2 text-left font-normal",
                  NII_PARTS.has(entry.category) && "pl-7 text-muted-foreground",
                )}
              >
                {CATEGORY_NAMES[entry.category] ?? entry.category}
              </th>
              <td className={cn(cell, "hidden text-muted-foreground sm:table-cell")}>{formatInteger(entry.offered)}</td>
              <td className={cn(cell, "hidden text-muted-foreground sm:table-cell")}>{formatInteger(entry.bid)}</td>
              <td className={cn(cell, entry.times != null && entry.times >= 1 && "text-positive")}>
                {formatTimes(entry.times) ?? MISSING}
              </td>
            </tr>
          ))}
          <tr>
            <th scope="row" className="px-3 py-2 text-left font-semibold">Total</th>
            <td className={cn(cell, "hidden sm:table-cell")} />
            <td className={cn(cell, "hidden sm:table-cell")} />
            <td className={cn(cell, "font-semibold")}>{formatTimes(row.subscription_total) ?? MISSING}</td>
          </tr>
        </tbody>
      </table>
      <p className="tabular mt-3 px-1 text-[11px] text-muted-foreground">
        {[
          "NSE + BSE",
          row.subscription_as_of ? formatDateTimeIST(row.subscription_as_of) : null,
          bookSize(row) ? `${formatMoneyCompact(bookSize(row), market)} offered, excl. anchor` : null,
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
    </div>
  );
}

/** The prospectus's restated figures, as the GMP tracker prints them: a row per line, a column per period. */
function FinancialsTable({ financials }: { financials: NonNullable<Ipo["financials"]> }) {
  const cell = "tabular whitespace-nowrap px-3 py-2 text-right font-mono text-[13px]";
  const basis = financials.basis ? financials.basis[0] + financials.basis.slice(1).toLowerCase() : null;
  return (
    <div className="-mx-1 overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">
          Restated financials from the prospectus{financials.unit ? `, in rupees ${financials.unit}` : ""}
        </caption>
        <thead>
          <tr className="whitespace-nowrap border-b text-[11px] text-muted-foreground">
            <th scope="col" className="px-3 py-2 text-left font-medium">Period ended</th>
            {financials.periods.map((period, i) => (
              <th key={period ?? i} scope="col" className="px-3 py-2 text-right font-medium">
                {periodLabel(period) ?? MISSING}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {financials.rows.map((row) => (
            <tr key={row.label} className="border-b last:border-0">
              <th scope="row" className="whitespace-nowrap px-3 py-2 text-left font-normal">{row.label}</th>
              {financials.periods.map((period, i) => (
                <td key={period ?? i} className={cell}>{formatNumber(row.values[i] ?? null, 2)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="tabular mt-3 px-1 text-[11px] text-muted-foreground">
        {[financials.unit ? `₹ ${financials.unit}` : null, basis, "investorgain.com"].filter(Boolean).join(" · ")}
      </p>
    </div>
  );
}

/** Points from the prospectus, in its order: a bold lead where it gives one. */
function PointList({ items, tone }: { items: { title: string | null; text: string | null }[]; tone: "positive" | "negative" }) {
  return (
    <ul className="space-y-3 text-sm leading-relaxed">
      {items.map((item, i) => (
        <li key={i} className="flex gap-3">
          <span
            aria-hidden
            className={cn("mt-[0.6em] size-1 shrink-0 rounded-full", tone === "positive" ? "bg-positive" : "bg-negative")}
          />
          <p className="max-w-prose text-pretty">
            {item.title ? (
              <span className="font-semibold">{/[.?!:]$/.test(item.title) ? item.title : `${item.title}.`} </span>
            ) : null}
            <span className={item.title ? "text-muted-foreground" : undefined}>{item.text}</span>
          </p>
        </li>
      ))}
    </ul>
  );
}

function Source({ label }: { label: string }) {
  return <p className="tabular mt-4 text-[11px] text-muted-foreground">{label}</p>;
}

/** The RHP's risk factors: the first few, the rest behind a closed disclosure. */
function RiskList({ risks }: { risks: RiskFactor[] }) {
  const { lead, more } = splitRisks(risks);
  return (
    <>
      <PointList items={lead} tone="negative" />
      {more.length ? (
        <details className="group/more mt-3">
          <summary className="-mx-2 inline-flex min-h-11 cursor-pointer items-center gap-1 rounded-md px-2 text-sm font-medium marker:content-none hover:bg-muted/60 focus-visible:outline-2 focus-visible:outline-ring">
            {more.length} more
            <ChevronRight
              aria-hidden
              className="size-4 transition-transform duration-200 ease-out group-open/more:rotate-90 motion-reduce:transition-none"
            />
          </summary>
          <div className="pt-2">
            <PointList items={more} tone="negative" />
          </div>
        </details>
      ) : null}
      <Source label="RHP" />
    </>
  );
}

/**
 * One issue: its book by category, the facts of the offer, the odds of a retail
 * allotment, the grey market (when switched on, labelled unofficial) and, once
 * listed, how it listed. Read from the same object as the list.
 */
export default async function IpoPage({ params }: PageProps<"/[market]/ipos/[symbol]">) {
  const { market: slug, symbol } = await params;
  const found = await findIssue(slug, symbol);
  if (!found) notFound();
  const { market, row } = found;

  const today = new Intl.DateTimeFormat("en-CA", { timeZone: market.timezone }).format(new Date());
  const status = issueStatus(row, today);
  const listed = status === "listed";
  const [now, risks] = await Promise.all([
    listed ? getPricesNow(market.code, [row.symbol]).then((prices) => prices.get(row.symbol) ?? null) : null,
    getRiskFactors(market.code, row.symbol),
  ]);
  const lot = minInvestment(row);
  const retail = categoryTimes(row, "Retail");
  const gmpDigits = (value: number | null) => (value != null && value % 1 ? 1 : 0);

  const facts: Field[] = [
    { label: row.issue_price != null ? "Issue price" : "Price band", value: priceBand(row, market) },
    { label: "Lot", value: row.lot_size ? `${formatInteger(row.lot_size)} shares` : MISSING },
    {
      label: "One lot costs",
      value: formatMoney(lot, market, 0),
      hint: row.issue_price == null && lot ? "At the top of the band" : undefined,
    },
    { label: "Bidding", value: `${formatDate(row.open_date)} to ${formatDate(row.close_date)}` },
    { label: "Board", value: row.board === "SME" ? "NSE Emerge (SME)" : (row.board ?? MISSING) },
    { label: "Face value", value: formatMoney(row.face_value, market, 0) },
    {
      label: "Registrar",
      value: row.registrar ?? MISSING,
      hint: row.registrar ? "Publishes the allotment status" : undefined,
    },
  ];

  const when =
    status === "upcoming"
      ? `Opens ${shortDate(row.open_date)}, closes ${shortDate(row.close_date)}`
      : status === "bidding"
        ? row.close_date === today
          ? "Bidding closes today at 5 pm"
          : `Bidding until ${shortDate(row.close_date)}, 5 pm`
        : status === "awaiting"
          ? `Bidding closed ${shortDate(row.close_date)}`
          : `Listed ${formatDate(row.listing_date)}`;

  return (
    <div className="space-y-4 px-4 py-5 sm:px-6">
      <div>
        <Link
          prefetch={false}
          href={marketPath(market.slug, "/ipos")}
          className="inline-flex items-center gap-1 rounded-md text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ArrowLeft className="size-3" aria-hidden />
          All IPOs
        </Link>
        <h1 className="sr-only">{row.company ?? row.symbol} IPO</h1>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
          <StockIdentity
            symbol={row.symbol}
            company={row.company}
            link={listed}
            size="md"
            emphasis="company"
            sme={row.board === "SME"}
          />
          <span className="inline-flex items-center gap-1.5 rounded-md bg-(--control) px-2 py-0.5 text-[11px] font-semibold text-muted-foreground">
            {status === "bidding" ? <LiveDot /> : null}
            {STATUS_LABEL[status]}
          </span>
        </div>
        <p className="tabular mt-1.5 text-sm text-muted-foreground">{when}</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] lg:items-start">
        <div className="space-y-4">
          {listed ? (
            <Panel title="Listing">
              <FieldList
                columns={2}
                fields={[
                  { label: "Listed", value: formatDate(row.listing_date) },
                  { label: "Listing open", value: <PriceAgainstIssue row={row} price={row.listing_open} market={market} /> },
                  { label: "Listing day close", value: <PriceAgainstIssue row={row} price={row.listing_close} market={market} /> },
                  { label: "Now", value: <PriceAgainstIssue row={row} price={now} market={market} /> },
                ]}
              />
            </Panel>
          ) : null}
          <Panel title="Subscription">
            {row.subscription?.length ? (
              <BookTable row={row} market={market} />
            ) : (
              <p className="text-sm text-muted-foreground">
                {status === "upcoming"
                  ? `Bidding opens ${shortDate(row.open_date)}; the book shows here within a quarter of an hour of the first bids.`
                  : "NSE has not published the shares on offer yet."}
              </p>
            )}
          </Panel>
          {!listed && retail != null ? (
            <Panel
              title="Odds of a retail allotment"
              info={
                <p>
                  Once the retail book is oversubscribed, each retail applicant can be allotted at most one lot,
                  drawn by lottery, so one application wins about once in the number of times the book is
                  subscribed. This assumes every bid is for one lot, as most are; larger bids make the real odds a
                  little better. Applications from the same PAN count once.
                </p>
              }
            >
              <AllotmentOdds retailTimes={retail} lotCost={lot} />
            </Panel>
          ) : null}
          {row.financials?.rows.length ? (
            <Panel title="Financials">
              <FinancialsTable financials={row.financials} />
            </Panel>
          ) : null}
          {row.strengths?.length ? (
            <Panel title="Strengths">
              <PointList items={row.strengths} tone="positive" />
              <Source label="RHP · investorgain.com" />
            </Panel>
          ) : null}
          {risks?.length ? (
            <Panel title="Risk factors">
              <RiskList risks={risks} />
            </Panel>
          ) : null}
        </div>

        <div className="space-y-4">
          <Panel title="The offer">
            <FieldList fields={facts} columns={2} />
          </Panel>
          {row.gmp != null && !listed ? (
            <Panel title="Grey market" tag="Unofficial">
              <FieldList
                columns={2}
                fields={[
                  {
                    label: "GMP now",
                    value: (
                      <>
                        {formatMoney(row.gmp, market, gmpDigits(row.gmp))}
                        <span className="ml-1.5 text-muted-foreground">{formatSignedPercent(row.gmp_pct, 1) ?? ""}</span>
                      </>
                    ),
                    tone: row.gmp > 0 ? "positive" : row.gmp < 0 ? "negative" : "default",
                  },
                  { label: "Highest so far", value: formatMoney(row.gmp_peak, market, gmpDigits(row.gmp_peak)) },
                  { label: "Updated", value: formatDateTimeIST(row.gmp_as_of) },
                  {
                    label: "Price plus GMP",
                    value: formatMoney(impliedListing(row), market, 0),
                    hint: "What the grey market implies, not a forecast",
                  },
                ]}
              />
              <p className="tabular mt-4 text-[11px] text-muted-foreground">
                investorgain.com
              </p>
            </Panel>
          ) : null}
          {row.rhp_url ? (
            <Panel title="Documents">
              <a
                href={row.rhp_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 rounded-md text-sm font-medium underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <FileText className="size-4 text-muted-foreground" aria-hidden />
                Red herring prospectus
                <span className="text-xs font-normal text-muted-foreground">NSE archive, zip</span>
              </a>
            </Panel>
          ) : null}
        </div>
      </div>
    </div>
  );
}
