# StockScans scan-builder filter catalog (read 22 Nov 2026)

Source: the field registry embedded in the `/scans/new` route chunk
(`_next/static/chunks/0liajt0mloje8.js`), read while signed in. Each field is
`name -> {type, shortname, unit?, description?}`; `type` is the picker's category.
408 visible fields (plus one hidden, `Name`). Every field used by their 37 public
scans (`/api/scans/stock/popular`) resolves to this list.

A filter is `left sign right`, where either side can be a field, a number, or an
arithmetic expression of fields (`+ - * / ()`), e.g.
`OPM Latest Quarter > OPM Preceding Year Quarter * 1.20`.

## Catalog

| Category | Fields |
|---|---|
| Price and Technical Indicators (163) | Market Capitalization, Close Price, Previous Close Price; Returns 1D/1W/1M/3M/6M/1Y/2Y/3Y/5Y/10Y/YTD, Returns Since IPO, Returns Since Result, Listed Days; SMA 20D/50D/100D/200D, 10W/21W/26W/30W/40W/52W, 6M/12M; EMA 10D/20D/50D/100D/200D, 10W/21W/26W/30W/40W/52W, 6M/12M; All Time High/Low, 5Y High/Low, 3Y High/Low, 52WH/52WL, 26WH/26WL, 13WH/13WL; Distances: 52WH, 52WL, 26WH, 13WH, 3Y High, 5Y High, All Time High (and "Days" variants), Breakout Window; Gap Opening; VSTOP (10D/10W/10M/14D/14W/12M at 2 and 2.5) and Last VSTOP Change; Last Golden/Death crossover 10W×30W and 50D×200D; MACD 12D 26D 9 Line/Signal/Last Change; Volume, Volume SMA 5D/10D/20D/50D/100D/200D; CRS vs Nifty 50/500 at 25D/50D/26W/52W/6M/12M; Returns vs Nifty 50, vs Nifty 500 (1W–5Y), vs Industry (1W–10Y); Nifty 50/500 and Industry returns (1W–10Y) |
| RS Scores (5) | RS Score; RS Score Change 1W/1M/3M/6M |
| Ratios (110) | P/E (now, 3Y/5Y back, median 3/5/10Y, growth 3/5Y), P/S (same set), Industry PE/PS Median, PEG, P/B, Book Value, EV, EV/EBITDA (now, 1Y back); NPM, OPM, GPM (latest quarter, 1–3 quarters back, preceding-year quarter, 1/3/5Y back, median 3/5Y); ROCE, ROE (now, 1/2Y back, median 3/5/7/10Y); ROA; Dividend, Dividend Yield, Payout; Asset Turnover; Days Inventory/Payable/Receivable, Cash Conversion Cycle (now to 3Y back); Debt to Equity (now to 3Y back); Interest Coverage; Inventory Turnover; CFO/PAT, CFO/EBITDA; Current, Quick Ratio; Equity Shares 1/2Y back |
| Income Statement (69) | Revenue, PAT, EPS, PBT, EBIT, EBITDA, Operating Profit, Expenses (annual, years back; quarterly: latest, 1–3 quarters back, preceding-year quarter); growth QoQ/YoY/TTM/3Y/5Y/10Y for Revenue, PAT, EPS, PBT, EBIT, EBITDA; Days From Result |
| Balance Sheet (21) | Equity Shares, Reserves, CWIP, Cash Equivalents, Total Assets, Fixed Assets (to 3Y back), Total Liabilities, Debt (to 3Y back), Inventory |
| Cash Flow (10) | Operating, Investing, Financing, Free, Net Cash Flow (now, 1Y back) |
| Share Holdings (25) | Promoter, FII, DII, Retail holdings; Change in each over latest quarter, 1Y, 2Y, 3Y; Pledged Percentage (now, 1 quarter back, 1Y back); Insider Trading (₹ Cr, last month); Bulk Block Deals (₹ Cr, last month) |
| Others (5) | Industry, Sector, Documents, Last Result Date, Next Result Date |

## Against Cupel's screener

| Area | Cupel has | Gap, and whether the data is already stored |
|---|---|---|
| Share Holdings | Promoter, FII, DII %; each rose/fell vs previous quarter | Retail % (`public`, stored); 1–3Y change (stored since Sep 2022); bulk/block deal value, last month (`bulk_block_deals`, stored); pledge and insider trading (not collected) |
| Results timing | Upcoming results on the stock page | Days From Result, Last/Next Result Date as filters (`upcoming_events`, `quarterly_filings`, stored) |
| Quarterly lines | Revenue/profit growth YoY | OPM/NPM latest vs preceding-year quarter, QoQ growth (`quarterly_filings`, stored) |
| Valuation | P/E, P/B, dividend yield | EV/EBITDA, P/S (`valuation_basis` holds EBITDA, revenue, debt, cash); historical medians (need multi-year history) |
| Returns | 1D–12M, 52W-high distance, RS rating, stage | Returns vs index/industry, 52W-low and all-time/5Y-high distance, listed days |
| Technical | RSI 14, above 200-day average, volatility, drawdown | Moving-average set, volume vs average, MACD, crossovers, gap opening |
| Statements | ROE, ROIC, D/E, growth | Cash-flow lines, CFO/PAT, working-capital days, multi-year growth and medians |
| Builder | One-column ranges | Field-vs-field expressions (PostgREST cannot compare two columns; needs a function or stored derived columns) |

Since 22 Nov 2026 a filter may read a key of D1's `extra` column (json_extract), so
D1's 100-column cap no longer limits filters. Added that day from stored data:
retail holding, 1-year holding changes, bulk/block deal flows (all and foreign),
days since/to results, EV/EBITDA, P/S, latest-quarter operating margin and its
move from the year-ago quarter.
