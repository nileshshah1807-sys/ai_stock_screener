// A company listed on BSE alone is carried in the NSE run under its Yahoo
// ticker, "SYMBOL.BO" (screener/universe.py), so the suffix names the
// exchange and is not part of the ticker a reader knows.
const BSE_SUFFIX = ".BO";

/** `"TANFACIND.BO"` -> `{ ticker: "TANFACIND", exchange: "BSE" }`. */
export function listing(symbol) {
  const text = String(symbol ?? "");
  return text.endsWith(BSE_SUFFIX)
    ? { ticker: text.slice(0, -BSE_SUFFIX.length), exchange: "BSE" }
    : { ticker: text, exchange: null };
}
