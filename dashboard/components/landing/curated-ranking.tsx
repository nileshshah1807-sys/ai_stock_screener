/*
 * The landing page's lead argument: a curated shortlist instead of a universe
 * to search. Each factor below is one the daily ranking really weighs
 * (screener/factors.py: value, momentum, risk; the earnings-call outlook in
 * screener/recommendation.py). No rating, return or recommendation appears.
 */

const FACTORS = [
  ["Management guidance", "For Indian companies, what management said on the earnings call about outlook, demand, margins and orders, compared with the previous call."],
  ["Value", "Earnings, free cash flow, operating profit and book value against the price, plus a discounted-cash-flow check."],
  ["Momentum", "Price trend over six and twelve months, adjusted for volatility, and strength against the market and the stock's own sector."],
  ["Risk", "Volatility, how deep past drawdowns ran, how often the stock trades and how sharp its overnight gaps are."],
];

export function CuratedRanking() {
  return (
    <div className="grid items-start gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:gap-14">
      <div>
        <h2 data-reveal className="text-title max-w-[22ch] text-balance">A curated shortlist, not a whole market to search</h2>
        <p className="mt-4 max-w-[52ch] text-sm leading-relaxed text-muted-foreground">
          Every evening Cupel measures each stock against the others in its market and narrows thousands of tickers to a short list worth opening. There is far less to search and filter, and the ranking is algorithmic: no one hand-picks names.
        </p>
        <p className="mt-4 max-w-[52ch] text-sm font-medium leading-relaxed">
          None of it is a buy or sell call, and it is not investment advice. It is a way to decide what to read first. Do your own research.
        </p>
      </div>
      <div>
        <dl data-stagger aria-label="What the ranking weighs" className="grid gap-x-8 gap-y-6 sm:grid-cols-2">
          {FACTORS.map(([name, body]) => (
            <div key={name} className="border-t pt-3">
              <dt className="text-lead font-semibold">{name}</dt>
              <dd className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{body}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-6 text-xs text-muted-foreground">Business quality and growth are weighed too. Companies are compared with their own market, never across it.</p>
      </div>
    </div>
  );
}
