import { listing } from "./listing.mjs";

// TradingView's free Advanced Chart widget, loaded in the viewer's browser:
// no Worker CPU, no data of ours. It refuses NSE symbols ("only available on
// TradingView", checked 20 Nov 2026), so an Indian stock is charted from its
// BSE listing (end-of-day) and a stock listed on NSE alone keeps our own chart.
export const WIDGET_SRC = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";

const TIME_ZONES = { NSE: "Asia/Kolkata", US: "America/New_York" };

/**
 * The widget's symbol for a stock, or null when it has none.
 *
 * NSE run: a `.BO` name is its BSE ticker; any other needs `bseSymbol`, the
 * BSE ticker the screener matched by ISIN (`BSE_Symbol` in the payload).
 * US: the ticker, with a share class written `BRK.B` as TradingView does.
 * TradingView writes `&` and `-` in a ticker as `_` (BSE:M_M, BSE:BAJAJ_AUTO).
 *
 * @param {string} market
 * @param {string} symbol
 * @param {unknown} bseSymbol
 * @returns {string | null}
 */
export function tradingViewSymbol(market, symbol, bseSymbol) {
  if (!symbol) return null;
  if (market === "US") return String(symbol).replace("-", ".");
  const { ticker, exchange } = listing(symbol);
  const bse = exchange === "BSE" ? ticker : typeof bseSymbol === "string" ? bseSymbol.trim() : "";
  return bse ? `BSE:${bse.replace(/[&-]/g, "_")}` : null;
}

/**
 * The widget's configuration: daily candles with its own indicators and
 * drawing tools, the symbol fixed to the page's stock.
 *
 * @param {string} symbol a `tradingViewSymbol` result
 * @param {string} market
 * @param {boolean} dark
 */
export function widgetConfig(symbol, market, dark) {
  return {
    autosize: true,
    symbol,
    interval: "D",
    timezone: TIME_ZONES[market] ?? "Etc/UTC",
    theme: dark ? "dark" : "light",
    style: "1",
    locale: "en",
    allow_symbol_change: false,
    hide_side_toolbar: false,
    withdateranges: true,
    save_image: false,
    calendar: false,
    details: false,
    support_host: "https://www.tradingview.com",
  };
}
