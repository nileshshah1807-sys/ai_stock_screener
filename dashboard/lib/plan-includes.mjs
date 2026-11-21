/**
 * What a subscription gets, as the plan card shows it everywhere it is sold
 * (/pricing signed in and out, the landing's pricing). Only what a viewer who
 * is not an admin can see today: never ratings, the model's rank or score, or
 * the Returns page (lib/ratings.mjs, lib/tools.ts). The test holds that.
 */
export const PRICING_LEAD = "One subscription covers both markets. Every plan includes everything below.";
export const PLAN_INCLUDES_HEADING = "What you get";
export const PLAN_INCLUDES = [
  ["Screener for India and the US", "NSE mainboard, SME and BSE-only companies, and the S&P 1500, updated every trading day"],
  ["Your score", "rank stocks by the factors you weight, and save your views to your account"],
  ["Stock pages", "financials and charts for every stock; for NSE stocks, also quarterly results from exchange filings, shareholding, and bulk and block deals"],
  ["Results", "each company's quarter as it files it, typically within minutes"],
  ["Concalls", "earnings calls of the season as they are recorded or filed, with management's stance in a word and the line behind it"],
  ["Market", "breadth, movers by index and live prices every five minutes in market hours"],
  ["Watchlists and alerts", "a bell for new results and call transcripts on the stocks you watch"],
];
