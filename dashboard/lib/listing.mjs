// A company listed on BSE alone is carried in the NSE run under its Yahoo
// ticker, "SYMBOL.BO" (screener/universe.py), so the suffix names the
// exchange and is not part of the ticker a reader knows.
export const BSE_SUFFIX = ".BO";

/**
 * `"TANFACIND.BO"` -> `{ ticker: "TANFACIND", exchange: "BSE", sme: false }`.
 * `sme` is the row's `is_sme` flag: an SME is tagged whichever exchange it is on.
 */
export function listing(symbol, sme = false) {
  const text = String(symbol ?? "");
  return text.endsWith(BSE_SUFFIX)
    ? { ticker: text.slice(0, -BSE_SUFFIX.length), exchange: "BSE", sme: sme === true }
    : { ticker: text, exchange: null, sme: sme === true };
}
