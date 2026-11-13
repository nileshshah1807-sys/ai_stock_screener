import { decodeRow, metricPoints } from "./market-breadth.mjs";
import { resultCard } from "./results.mjs";
import { SITE_URL } from "./seo.mjs";

/** The stage label the screener writes (screener/stage.py STAGE_2). */
const STAGE_2 = "Stage 2";

/**
 * Every key the digest may carry, by section. A test holds the output to
 * these: no rating, rank, score or return may ever leave in it, because the
 * data licence for redistribution is undecided.
 */
export const DIGEST_KEYS = {
  top: ["as_of", "market", "results", "concalls", "stage2", "breadth", "upcoming"],
  results: ["symbol", "name", "quarter", "revenue_yoy_pct", "profit_yoy_pct", "filed_at", "page_url"],
  concalls: ["symbol", "name", "call_date", "stance_band", "outlook_quote", "page_url"],
  stage2: ["count", "change_vs_prev", "new_entrants"],
  entrant: ["symbol", "name"],
  breadth: ["pct_above_50ema", "pct_above_200ema", "advancers", "decliners", "new_52w_highs", "new_52w_lows"],
  upcoming: ["symbol", "name", "result_date", "page_url"],
};

const oneDecimal = (value) => (value == null ? null : Math.round(value * 10) / 10);

/**
 * The day's digest for a market, from rows the existing read paths return.
 *
 * `feed` is the results feed's entries, `filings` their quarters' filings,
 * `calls` concall_feed rows, `breadthRow` the market row of market_breadth,
 * `snapshot` the latest run's `{ symbol, company, stage, days_in_stage,
 * pct_change_1d }`, `upcoming` upcoming_events rows due by `through`.
 */
export function digestFrom({ market, slug, today, through, feed, filings, calls, breadthRow, snapshot, upcoming }) {
  const page = (symbol) => `${SITE_URL}/${slug}/stocks/${encodeURIComponent(symbol)}`;
  const names = new Map(snapshot.map((row) => [row.symbol, row.company ?? null]));
  const nameOf = (symbol, own) => own ?? names.get(symbol) ?? null;

  const filingsOf = new Map();
  for (const filing of filings) filingsOf.set(filing.symbol, [...(filingsOf.get(filing.symbol) ?? []), filing]);
  const results = feed.map((entry) => {
    const rows = resultCard(entry, filingsOf.get(entry.symbol) ?? [], entry.period_end).bases[0]?.rows ?? [];
    const yoy = (key) => oneDecimal(rows.find((row) => row.key === key)?.yoy ?? null);
    return {
      symbol: entry.symbol,
      name: nameOf(entry.symbol, entry.company),
      quarter: entry.period_end,
      revenue_yoy_pct: yoy("revenue"),
      profit_yoy_pct: yoy("net_profit"),
      filed_at: entry.announced_at,
      page_url: page(entry.symbol),
    };
  });

  const concalls = calls.map((call) => ({
    symbol: call.symbol,
    name: nameOf(call.symbol, call.company),
    call_date: call.call_date,
    stance_band: call.management_stance ?? null,
    outlook_quote: call.management_stance_quote ?? null,
    page_url: page(call.symbol),
  }));

  const decoded = decodeRow(breadthRow);
  const last = (key) => decoded?.series?.[key]?.at(-1) ?? null;
  const share = (key) => oneDecimal(metricPoints(decoded, key, `${key}d`, "share").at(-1)?.value ?? null);
  const stage2Counts = decoded?.series?.s2 ?? [];
  const stage2 = {
    count: last("s2"),
    change_vs_prev: stage2Counts.length > 1 ? stage2Counts.at(-1) - stage2Counts.at(-2) : null,
    // Days_In_Stage is calendar days since the stage began: 0 means it began on the run's session.
    new_entrants: snapshot
      .filter((row) => row.stage === STAGE_2 && row.days_in_stage === 0)
      .map((row) => ({ symbol: row.symbol, name: row.company ?? null })),
  };
  const moved = snapshot.map((row) => row.pct_change_1d).filter((change) => typeof change === "number");
  const breadth = {
    pct_above_50ema: share("e50"),
    pct_above_200ema: share("e200"),
    advancers: moved.length ? moved.filter((change) => change > 0).length : null,
    decliners: moved.length ? moved.filter((change) => change < 0).length : null,
    new_52w_highs: last("hi"),
    new_52w_lows: last("lo"),
  };

  const due = upcoming
    .filter((row) => row.next_result_date && row.next_result_date >= today && row.next_result_date <= through)
    .sort((a, b) => a.next_result_date.localeCompare(b.next_result_date) || a.symbol.localeCompare(b.symbol))
    .map((row) => ({ symbol: row.symbol, name: nameOf(row.symbol), result_date: row.next_result_date, page_url: page(row.symbol) }));

  return { as_of: today, market, results, concalls, stage2, breadth, upcoming: due };
}
