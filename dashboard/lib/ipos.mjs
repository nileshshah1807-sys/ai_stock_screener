/**
 * The IPOs page's rules, pure so they are tested (ipos.test.mjs).
 *
 * Rows are workers/ipos.py's, from `live/NSE/ipos.json`: NSE's issues with the
 * combined NSE+BSE book by category, the listing day's open and close, and --
 * only when the GMP switch is on -- the grey-market premium a public tracker
 * prints. Dates are ISO days in India time; `today` is too.
 */

/** Risk factors shown before the rest fold away: an RHP states 70-100. */
export const RISKS_SHOWN = 5;

/** The first `shown` risk factors, and the rest for a closed disclosure. */
export function splitRisks(risks, shown = RISKS_SHOWN) {
  const all = risks ?? [];
  return { lead: all.slice(0, shown), more: all.slice(shown) };
}

/** Where an issue stands today. */
export function issueStatus(row, today) {
  if (row.listing_date && row.listing_date <= today) return "listed";
  if (row.open_date && today < row.open_date) return "upcoming";
  if (row.close_date && today > row.close_date) return "awaiting";
  return row.open_date ? "bidding" : "upcoming";
}

export const STATUS_LABEL = {
  bidding: "Bidding",
  upcoming: "Upcoming",
  awaiting: "Awaiting listing",
  listed: "Listed",
};

/** Sections in reading order: what can be bid on now first; listed issues newest first. */
export function groupIssues(rows, today) {
  const groups = { bidding: [], upcoming: [], awaiting: [], listed: [] };
  for (const row of rows) groups[issueStatus(row, today)].push(row);
  const by = (key, dir) => (a, b) => dir * String(a[key] ?? "").localeCompare(String(b[key] ?? ""));
  groups.bidding.sort(by("close_date", 1));
  groups.upcoming.sort(by("open_date", 1));
  groups.awaiting.sort(by("close_date", -1));
  groups.listed.sort(by("listing_date", -1));
  return groups;
}

/** The board filter's options, in the order shown; `all` is the unfiltered list. */
export const BOARDS = [
  { value: "all", label: "All" },
  { value: "mainboard", label: "Mainboard" },
  { value: "sme", label: "SME" },
];

/** The `?board=` value as one of BOARDS; anything else is "all". */
export function boardParam(value) {
  return BOARDS.some((board) => board.value === value) ? value : "all";
}

/** The issues on one board; an issue whose board NSE did not name shows only under "all". */
export function onBoard(rows, board) {
  if (board === "all") return rows;
  const name = board === "sme" ? "SME" : "Mainboard";
  return rows.filter((row) => row.board === name);
}

/** The list page's query: "?board=sme&listed=all", "" for the default view. */
export function listQuery(board, showAll) {
  const params = new URLSearchParams();
  if (board !== "all") params.set("board", board);
  if (showAll) params.set("listed", "all");
  const text = params.toString();
  return text ? `?${text}` : "";
}

/**
 * The listed table's optional columns that have a value in some row shown: a
 * column of dashes alone is left out. `prices` is the page's map of today's prices.
 */
export function listedColumns(rows, prices) {
  return {
    subscribed: rows.some((row) => row.subscription_total != null),
    now: rows.some((row) => prices.has(row.symbol)),
  };
}

/** The book's ratio for one category ("QIB", "NII", "Retail", ...), or null when it has none. */
export function categoryTimes(row, category) {
  return (row.subscription ?? []).find((entry) => entry.category === category)?.times ?? null;
}

/** The price an applicant pays: the issue price once fixed, else the top of the band. */
export function applicationPrice(row) {
  return row.issue_price ?? row.price_high ?? null;
}

/** Rupees blocked by one lot at the application price. */
export function minInvestment(row) {
  const price = applicationPrice(row);
  return row.lot_size && price ? row.lot_size * price : null;
}

/** The book (anchor portion excluded) at the application price, in rupees. */
export function bookSize(row) {
  const price = applicationPrice(row);
  return row.book_shares && price ? row.book_shares * price : null;
}

/** Percent change from the issue price to `price`, or null. */
export function changeFromIssue(row, price) {
  const issue = applicationPrice(row);
  return issue && price != null ? ((price - issue) / issue) * 100 : null;
}

/** The application price plus the grey-market premium: what the tracker implies, not a forecast. */
export function impliedListing(row) {
  const price = applicationPrice(row);
  return price != null && row.gmp != null ? price + row.gmp : null;
}

/**
 * Chance of at least one lot with `applications` retail applications from
 * different PANs, when the retail book ends `times` subscribed.
 *
 * Oversubscribed, SEBI's rule gives each retail applicant at most one minimum
 * lot, drawn by lottery, so one application wins with about 1/times. That
 * assumes every bid is for the minimum lot, as most are; larger bids make the
 * real odds a little better. At or under 1x everyone is allotted.
 */
export function allotmentOdds(times, applications = 1) {
  if (times == null || !(times > 0) || !(applications >= 1)) return null;
  if (times <= 1) return 1;
  return 1 - (1 - 1 / times) ** Math.floor(applications);
}

/** `1.4` -> "1.40×"; null -> null, for the caller's dash. */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** When the tracker last moved a GMP: "11:02" today, "18 Nov, 19:37" before. The stamp is India time already. */
export function gmpStamp(asOf, today) {
  if (!asOf) return null;
  const time = asOf.slice(11, 16);
  return asOf.slice(0, 10) === today ? time : `${Number(asOf.slice(8, 10))} ${MONTHS[Number(asOf.slice(5, 7)) - 1]}, ${time}`;
}

/** A financial period's column head: "Jun 2026". */
export function periodLabel(iso) {
  return iso ? `${MONTHS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}` : null;
}

export function formatTimes(value) {
  if (value == null || !Number.isFinite(value)) return null;
  return `${value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}×`;
}

/** "+6.99%", "−5.00%" with a true minus; null for null. */
export function formatSignedPercent(value, digits = 1) {
  if (value == null || !Number.isFinite(value)) return null;
  const text = Math.abs(value).toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${text}%`;
}
