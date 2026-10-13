/**
 * The filters a feed of company events is narrowed by -- Notifications and
 * Concalls today -- and their one spelling in the URL.
 *
 * A feed row carries a symbol and little else, so every filter here resolves
 * to a set of symbols from the latest published run: the companies whose facts
 * pass the rules and whose industry is selected. The feed is then read for
 * those symbols. Kept free of React and of the Supabase client so parsing,
 * the defaults and the matching can be tested directly (see the .test.mjs
 * beside this).
 */

/**
 * A size is typed in the unit a reader of that market quotes it in: crore of
 * rupees, millions of dollars. `market_cap` and turnover are stored in
 * currency units.
 */
export const SIZE_UNITS = {
  NSE: { factor: 1e7, suffix: "Cr", symbol: "₹", locale: "en-IN" },
  US: { factor: 1e6, suffix: "M", symbol: "$", locale: "en-US" },
};

/**
 * What a rule can compare. `field` is the name the fact travels under in
 * `matchSymbols`' input; `size` marks a figure typed in the market's unit.
 */
export const RULE_METRICS = [
  { value: "mcap", label: "Market cap", field: "market_cap", size: true },
  { value: "turnover", label: "Median daily turnover", field: "turnover", size: true },
  { value: "pe", label: "P/E", field: "pe_ratio", size: false },
  { value: "score", label: "Decision score", field: "decision_score", size: false },
];

export const RULE_OPERATORS = [
  { value: "gte", label: "≥" },
  { value: "lte", label: "≤" },
];

export const MAX_RULES = 6;
/** Spelled out when the viewer removed every rule, the default included. */
const NO_RULES = "none";

/** The size floor a whole-market feed opens with, in the market's unit. */
const DEFAULT_MIN_CAP = { NSE: 1000, US: 1000 };

/** @typedef {"NSE" | "US"} MarketCode */
/** @typedef {{ metric: string, op: string, value: number }} FilterRule */
/**
 * @typedef {object} EventFilters
 * @property {FilterRule[]} rules
 * @property {string[]} industries
 * @property {string[]} lists  The ids of the watchlists the feed is scoped to; none is the whole market.
 * @property {Record<string, string[]>} facets  The page's own facets, by search param.
 */
/**
 * @typedef {object} FilterContext
 * @property {MarketCode} market
 * @property {string[]} [listIds]
 * @property {"all" | "watchlists"} [defaultScope]
 * @property {Array<{ param: string, options: Array<{ value: string }> }>} [facets]
 */
/** @typedef {{ symbol: string, industry?: string | null } & Record<string, unknown>} Company */

const metric = (value) => RULE_METRICS.find((item) => item.value === value);

function list(value) {
  if (value === undefined || value === null || value === "") return [];
  return (Array.isArray(value) ? value : [value]).filter(
    (item) => typeof item === "string" && item !== "",
  );
}

/**
 * The rules a feed opens with when the URL names none.
 *
 * A whole market in a results season is hundreds of filings a day, most from
 * companies too small to act on, so it opens above a size floor. A feed scoped
 * to the viewer's watchlists opens with none: they chose those companies, and
 * a floor would hide the small ones the bell has just counted.
 *
 * @param {MarketCode} market
 * @param {boolean} scoped
 * @returns {FilterRule[]}
 */
export function defaultRules(market, scoped) {
  const floor = DEFAULT_MIN_CAP[market];
  if (scoped || !floor) return [];
  return [{ metric: "mcap", op: "gte", value: floor }];
}

function sameRules(a, b) {
  return (
    a.length === b.length &&
    a.every(
      (rule, index) =>
        rule.metric === b[index].metric && rule.op === b[index].op && rule.value === b[index].value,
    )
  );
}

function parseRule(text) {
  const [name, op, ...rest] = String(text).split(".");
  const amount = rest.join(".").trim();
  const value = Number(amount);
  if (!metric(name) || !RULE_OPERATORS.some((item) => item.value === op)) return null;
  if (amount === "" || !Number.isFinite(value)) return null;
  return { metric: name, op, value };
}

/**
 * Filters from a page's search params.
 *
 * `context` is what the URL is read against: the market, the viewer's list
 * ids, whether the page opens on their watchlists (`defaultScope`), and the
 * page's own facets (`[{ param, options: [{ value }] }]`). Anything the URL
 * names that the context does not know is dropped, so a stale link narrows to
 * what still exists rather than to nothing.
 *
 * @param {Record<string, string | string[] | undefined> | null | undefined} params
 * @param {FilterContext} context
 * @returns {EventFilters}
 */
export function parseEventFilters(params, context) {
  const { market, listIds = [], defaultScope = "all", facets = [] } = context;
  const query = params ?? {};

  const named = list(query.list).filter((id) => listIds.includes(id));
  const scope = list(query.scope)[0];
  let lists;
  if (named.length) lists = named;
  else if (scope === "all") lists = [];
  else if (scope === "watchlists") lists = [...listIds];
  else lists = defaultScope === "watchlists" ? [...listIds] : [];

  const raw = list(query.f).flatMap((item) => item.split(","));
  let rules;
  if (raw.length === 0) rules = defaultRules(market, lists.length > 0);
  else if (raw.includes(NO_RULES)) rules = [];
  else rules = raw.map(parseRule).filter(Boolean).slice(0, MAX_RULES);

  const chosen = {};
  for (const facet of facets) {
    const known = new Set(facet.options.map((option) => option.value));
    chosen[facet.param] = [...new Set(list(query[facet.param]).filter((item) => known.has(item)))];
  }

  return { rules, industries: [...new Set(list(query.industry))], lists, facets: chosen };
}

/**
 * The search-param entries that spell `filters`, as `[key, value]` pairs.
 *
 * Only what differs from the page's default is written, so the plain URL is
 * the default view and a link made before these filters existed still means
 * what it meant.
 *
 * @param {EventFilters} filters
 * @param {FilterContext} context
 * @returns {Array<[string, string]>}
 */
export function eventFilterEntries(filters, context) {
  const { market, listIds = [], defaultScope = "all", facets = [] } = context;
  const entries = [];

  const lists = filters.lists.filter((id) => listIds.includes(id));
  const every = listIds.length > 0 && lists.length === listIds.length;
  if (defaultScope === "watchlists") {
    if (lists.length === 0) {
      if (listIds.length) entries.push(["scope", "all"]);
    } else if (!every) {
      for (const id of lists) entries.push(["list", id]);
    }
  } else {
    for (const id of lists) entries.push(["list", id]);
  }

  if (!sameRules(filters.rules, defaultRules(market, lists.length > 0))) {
    entries.push([
      "f",
      filters.rules.length
        ? filters.rules.map((rule) => `${rule.metric}.${rule.op}.${rule.value}`).join(",")
        : NO_RULES,
    ]);
  }

  for (const industry of filters.industries) entries.push(["industry", industry]);
  for (const facet of facets) {
    for (const value of filters.facets?.[facet.param] ?? []) entries.push([facet.param, value]);
  }
  return entries;
}

/**
 * Every search param the filters own, for a caller replacing them in a URL.
 *
 * @param {FilterContext} context
 * @returns {string[]}
 */
export function eventFilterParams(context) {
  return ["f", "industry", "list", "scope", ...(context.facets ?? []).map((facet) => facet.param)];
}

/**
 * Whether `filters` is what the page shows with a plain URL.
 *
 * @param {EventFilters} filters
 * @param {FilterContext} context
 */
export function isDefaultView(filters, context) {
  return eventFilterEntries(filters, context).length === 0;
}

function passes(rule, company, market) {
  const definition = metric(rule.metric);
  const stored = company?.[definition.field];
  // An unreported figure passes no rule: a floor cannot vouch for a size it
  // was never told, and a ceiling cannot either.
  if (typeof stored !== "number" || !Number.isFinite(stored)) return false;
  const bound = definition.size ? rule.value * SIZE_UNITS[market].factor : rule.value;
  return rule.op === "gte" ? stored >= bound : stored <= bound;
}

/**
 * The symbols that pass the rules and the industry selection, or null when
 * neither narrows anything.
 *
 * `companies` is the latest run: `[{ symbol, industry, market_cap, ... }]`. A
 * company the run does not hold has no facts to test, so it is not in the
 * result -- a feed row for it shows only when nothing here is active.
 *
 * @param {Company[] | null | undefined} companies
 * @param {Pick<EventFilters, "rules" | "industries">} filters
 * @param {MarketCode} market
 * @returns {Set<string> | null}
 */
export function matchSymbols(companies, filters, market) {
  const industries = new Set(filters.industries);
  if (!filters.rules.length && !industries.size) return null;
  const symbols = new Set();
  for (const company of companies ?? []) {
    if (industries.size && !industries.has(company.industry)) continue;
    if (!filters.rules.every((rule) => passes(rule, company, market))) continue;
    symbols.add(company.symbol);
  }
  return symbols;
}

/**
 * Both restrictions at once; null means "no restriction", as it does for each.
 *
 * @param {Set<string> | null | undefined} a
 * @param {Iterable<string> | null | undefined} b
 * @returns {Set<string> | null}
 */
export function intersectSymbols(a, b) {
  if (a === null || a === undefined) return b ? new Set(b) : null;
  if (b === null || b === undefined) return a;
  const other = b instanceof Set ? b : new Set(b);
  return new Set([...a].filter((symbol) => other.has(symbol)));
}

/**
 * The same filters scoped to other watchlists.
 *
 * Rules still at the default follow the scope to its default -- the floor
 * comes off when a list is chosen and returns with the whole market -- while
 * rules the viewer set themselves stay as set.
 *
 * @param {EventFilters} filters
 * @param {string[]} lists
 * @param {MarketCode} market
 * @returns {EventFilters}
 */
export function withLists(filters, lists, market) {
  const untouched = sameRules(filters.rules, defaultRules(market, filters.lists.length > 0));
  return {
    ...filters,
    lists,
    rules: untouched ? defaultRules(market, lists.length > 0) : filters.rules,
  };
}

/**
 * The symbols a feed is read for, or null for all of them.
 *
 * `watchlists` is the viewer's lists, `[{ id, symbols }]`. `companies` is the
 * latest run, or null when it could not be read -- in which case rules and
 * industries have nothing to be tested against and are not applied, rather
 * than emptying the feed.
 *
 * @param {EventFilters} filters
 * @param {Array<{ id: string, symbols: string[] }>} watchlists
 * @param {Company[] | null} companies
 * @param {MarketCode} market
 * @returns {string[] | null}
 */
export function feedSymbols(filters, watchlists, companies, market) {
  const watched = filters.lists.length
    ? new Set(
        watchlists.filter((item) => filters.lists.includes(item.id)).flatMap((item) => item.symbols),
      )
    : null;
  const matched = companies ? matchSymbols(companies, filters, market) : null;
  const symbols = intersectSymbols(matched, watched);
  return symbols ? [...symbols] : null;
}

/**
 * Industries in the run with how many companies each holds, by name.
 *
 * @param {Company[] | null | undefined} companies
 * @returns {Array<{ value: string, label: string, count: number }>}
 */
export function industryOptions(companies) {
  const counts = new Map();
  for (const company of companies ?? []) {
    if (!company.industry) continue;
    counts.set(company.industry, (counts.get(company.industry) ?? 0) + 1);
  }
  return [...counts]
    .map(([value, count]) => ({ value, label: value, count }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/**
 * "Market cap ≥ ₹1,000 Cr".
 *
 * @param {FilterRule} rule
 * @param {MarketCode} market
 * @returns {string}
 */
export function ruleLabel(rule, market) {
  const definition = metric(rule.metric);
  const operator = RULE_OPERATORS.find((item) => item.value === rule.op);
  if (!definition || !operator) return "";
  const unit = SIZE_UNITS[market];
  const amount = Number(rule.value).toLocaleString(unit.locale);
  return definition.size
    ? `${definition.label} ${operator.label} ${unit.symbol}${amount} ${unit.suffix}`
    : `${definition.label} ${operator.label} ${amount}`;
}
