/**
 * The live reads worked out from the R2 live objects, in the shapes the
 * Supabase objects they replace returned, so the browser code is unchanged:
 * `valuation` is the `live_valuation` view (storage/valuation_basis_schema.sql),
 * `liveMarket` and `liveBreadth` the `live_market` (live_quotes_schema.sql) and
 * `live_breadth` (market_breadth_schema.sql) functions. No rating is returned:
 * these reach the browser.
 */

const number = (value) => (value === null || value === undefined || value === "" ? null : Number(value));
const ratio = (top, bottom) => (top === null || bottom === null || bottom === 0 ? null : top / bottom);
const max = (a, b) => (b && (!a || b > a) ? b : a);

/** The newest stock session and its times, as the functions' `latest` CTE. */
export function latest(quotes) {
  let session = null;
  let fetched_at = null;
  let traded_at = null;
  for (const quote of quotes) {
    if (quote.kind !== "stock") continue;
    session = max(session, quote.session);
    fetched_at = max(fetched_at, quote.fetched_at);
    traded_at = max(traded_at, quote.traded_at);
  }
  return { session, fetched_at, traded_at };
}

const QUOTE_FIELDS = ["symbol", "price", "change_pct", "volume", "traded_at", "session", "fetched_at"];

/** A quote as the `live_quotes` row a reader selects. */
export function quoteRow(quote) {
  return Object.fromEntries(QUOTE_FIELDS.map((field) => [field, quote[field] ?? null]));
}

/** A stock quote with the price ratios at it; `basis` is its valuation_basis row, if any. */
export function valuation(quote, basis) {
  const price = number(quote.price);
  // A withheld change (a change of unit) has no ratios, as the view's unit_price.
  const unit = number(quote.change_pct) !== null && price > 0 ? price : null;
  const shares = number(basis?.shares_outstanding);
  const marketCap = unit !== null && shares !== null && shares > 0 ? unit * shares : null;
  const debt = number(basis?.total_debt);
  const cash = number(basis?.total_cash);
  return {
    ...quoteRow(quote),
    market_cap: marketCap,
    pe_ratio: ratio(marketCap, number(basis?.net_profit_ttm)),
    pb_ratio: ratio(marketCap, number(basis?.book_equity)),
    ev_ebitda: marketCap === null || debt === null || cash === null ? null : ratio(marketCap + debt - cash, number(basis?.ebitda_ttm)),
  };
}

const bySymbol = (a, b) => (a.symbol < b.symbol ? -1 : a.symbol > b.symbol ? 1 : 0);

/**
 * Movers by index. `members` are index_members rows; `rated` the symbols with
 * a row in the latest run (a stock page to link to).
 */
export function liveMarket(quotes, members, limit, rated) {
  const now = latest(quotes);
  const stocks = new Map();
  const levels = new Map();
  for (const quote of quotes) {
    if (quote.session !== now.session) continue;
    if (quote.kind === "stock" && number(quote.change_pct) !== null) stocks.set(quote.symbol, quote);
    if (quote.kind === "index") levels.set(quote.symbol, quote);
  }
  const groups = new Map();
  for (const member of members) {
    const group = groups.get(member.index_name) ?? { position: Infinity, members: 0, quoted: [] };
    group.members += 1;
    group.position = Math.min(group.position, member.position ?? Infinity);
    const quote = stocks.get(member.symbol);
    if (quote) group.quoted.push({ symbol: member.symbol, company: member.company ?? null, price: number(quote.price), change_pct: number(quote.change_pct) });
    groups.set(member.index_name, group);
  }
  const mover = (row) => ({ ...row, rated: rated.has(row.symbol), rating: null });
  const indices = [...groups.entries()]
    .sort(([, a], [, b]) => a.position - b.position)
    .map(([name, group]) => {
      const up = [...group.quoted].sort((a, b) => b.change_pct - a.change_pct || bySymbol(a, b));
      const down = [...group.quoted].sort((a, b) => a.change_pct - b.change_pct || bySymbol(a, b));
      const level = levels.get(name);
      return {
        name,
        members: group.members,
        level: level ? number(level.price) : null,
        change_pct: level ? number(level.change_pct) : null,
        advances: group.quoted.filter((row) => row.change_pct > 0).length,
        declines: group.quoted.filter((row) => row.change_pct < 0).length,
        unchanged: group.quoted.filter((row) => row.change_pct === 0).length,
        gainers: up.slice(0, limit).filter((row) => row.change_pct > 0).map(mover),
        losers: down.slice(0, limit).filter((row) => row.change_pct < 0).map(mover),
      };
    });
  return { ...now, indices };
}

/**
 * Live breadth counts for one group. `levels` are market_breadth_levels rows,
 * `charted` the session the published charts end on (the market row's
 * last_session): levels of any other session give no counts.
 */
export function liveBreadth(quotes, levels, charted, scope, name) {
  const now = latest(quotes);
  const group = levels.filter(
    (level) =>
      level.as_of === charted &&
      (scope === "market" || (scope === "sector" && level.sector === name) || (scope === "industry" && level.industry === name)),
  );
  const current = new Map(quotes.filter((quote) => quote.session === now.session).map((quote) => [`${quote.kind}:${quote.symbol}`, quote]));
  const benchLevel = group.find((level) => level.bench_label && number(level.bench_base) > 0);
  const benchQuote = benchLevel ? current.get(`index:${benchLevel.bench_label}`) : null;
  const bench = benchQuote ? number(benchQuote.price) / number(benchLevel.bench_base) : null;
  const traded = [];
  for (const level of group) {
    const quote = current.get(`stock:${level.symbol}`);
    if (quote && quote.session > level.as_of && number(quote.change_pct) !== null) traded.push({ level, price: number(quote.price) });
  }
  const count = (test) => traded.filter(test).length;
  const known = (key) => count(({ level }) => number(level[key]) !== null);
  const above = (key) => count(({ level, price }) => number(level[key]) !== null && price > number(level[key]));
  const counts = traded.length
    ? {
        n: traded.length,
        e20: above("e20"), e20d: known("e20"),
        e50: above("e50"), e50d: known("e50"),
        e100: above("e100"), e100d: known("e100"),
        e200: above("e200"), e200d: known("e200"),
        hi: above("hi"),
        lo: count(({ level, price }) => number(level.lo) !== null && price < number(level.lo)),
        hld: known("hi"),
        // price / base - 1 > benchmark / bench_base - 1, rearranged.
        bb: bench === null ? 0 : count(({ level, price }) => number(level.base) !== null && price / number(level.base) > bench),
        bbd: bench === null ? 0 : known("base"),
      }
    : null;
  return { ...now, as_of: group.reduce((at, level) => max(at, level.as_of), null), counts };
}
