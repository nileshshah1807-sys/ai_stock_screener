# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Self-directed equity investors in India (NSE, including SME and BSE-only names) and the US (S&P 1500), on one paid plan (₹999 a year, 7-day trial). They come back daily: after the close to see what moved and why, during results season to read filings and calls, and when shortlisting stocks to research.

## Product Purpose
Cupel is a daily equity research screener for two markets. It gathers evidence from filings, prices and earnings calls and lets each viewer rank stocks by the factors they weight ("Your score"). Success is a viewer finding, in one visit, the companies worth their research time and the evidence behind them.

## Positioning
Ranking by the viewer's own factor weights, with coverage-normalised factors (a number a company never reported never counts against it); valuation ratios at the live price from the company's own filings; India and the US in one plan.

## Operating Context
A signed-in Next.js dashboard at cupel.in, routes under `/ind` and `/us`: screener, stock pages, Market (breadth, movers, indices), Results, Concalls, watchlists. Data is published by scheduled workers; live prices refresh every five minutes in the browser during the session.

## Capabilities and Constraints
- The dashboard Worker runs on Cloudflare Workers Free (10 ms CPU per request). No per-request server work, polling or timed refresh; anything live is read in the browser. No Workers Paid plan.
- The model's rank and score are shown to no one until SEBI registration; buy/sell ratings and Returns are admin-only.
- Every read is scoped to one market: a symbol does not identify a company across exchanges.
- Absent evidence is not a zero: missing values read "—" or "Unavailable", never 0.
- Market-wide and sector figures are display evidence; nothing on these pages feeds a score.

## Brand Commitments
Name Cupel. Typefaces Geist and Geist Mono. Plain, exact copy that says where a number comes from.

## Evidence on Hand
Real published data only (snapshot, price series, filings, breadth). No testimonials, customer counts or performance claims exist; none may be invented.

## Product Principles
1. Show where every number comes from.
2. A missing number is marked missing, never filled.
3. The viewer ranks; the product does not recommend.
4. Cheap to serve: static or browser-read, never a heavier server.
