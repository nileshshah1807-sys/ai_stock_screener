import assert from "node:assert/strict";
import test from "node:test";

import { tradingViewSymbol, widgetConfig } from "./tradingview.mjs";

test("an NSE stock is charted from its BSE listing, matched by ISIN", () => {
  assert.equal(tradingViewSymbol("NSE", "RELIANCE", "RELIANCE"), "BSE:RELIANCE");
  assert.equal(tradingViewSymbol("NSE", "SOMENSE", "OTHERBSE"), "BSE:OTHERBSE");
});

test("an NSE stock with no BSE listing has no widget symbol", () => {
  assert.equal(tradingViewSymbol("NSE", "NSEONLY", null), null);
  assert.equal(tradingViewSymbol("NSE", "NSEONLY", undefined), null);
  assert.equal(tradingViewSymbol("NSE", "NSEONLY", ""), null);
});

test("a BSE-only name is its own BSE ticker", () => {
  assert.equal(tradingViewSymbol("NSE", "TANFACIND.BO", null), "BSE:TANFACIND");
});

test("ampersands and hyphens are written as TradingView writes them", () => {
  assert.equal(tradingViewSymbol("NSE", "M&M", "M&M"), "BSE:M_M");
  assert.equal(tradingViewSymbol("NSE", "BAJAJ-AUTO", "BAJAJ-AUTO"), "BSE:BAJAJ_AUTO");
});

test("a US ticker passes through, its share class with a dot", () => {
  assert.equal(tradingViewSymbol("US", "AAPL", null), "AAPL");
  assert.equal(tradingViewSymbol("US", "BRK-B", null), "BRK.B");
});

test("the widget is fixed to the page's stock, in the page's theme and market time", () => {
  const config = widgetConfig("BSE:RELIANCE", "NSE", true);
  assert.equal(config.symbol, "BSE:RELIANCE");
  assert.equal(config.allow_symbol_change, false);
  assert.equal(config.theme, "dark");
  assert.equal(config.timezone, "Asia/Kolkata");
  assert.equal(widgetConfig("AAPL", "US", false).timezone, "America/New_York");
  assert.equal(widgetConfig("AAPL", "US", false).theme, "light");
});
