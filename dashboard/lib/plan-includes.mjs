/**
 * What a subscription gets, as the plan card shows it everywhere it is sold
 * (/pricing signed in and out, the landing's pricing). Only what a viewer who
 * is not an admin can see today: never ratings, the model's rank or score, or
 * the Returns page (lib/ratings.mjs, lib/tools.ts). The test holds that.
 */
export const PLAN_INCLUDES = [
  ["Screener for India and the US", "every NSE company, SME and BSE-only names included, and the S&P 1500, updated every trading day"],
  ["Your score", "rank stocks by the factors you weight, and save your views to your account"],
  ["Stock pages", "quarterly results from exchange filings, financials, shareholding, bulk and block deals, and charts"],
  ["Results", "each company's quarter as it files it, within minutes"],
  ["Concalls", "every earnings call of the season, with management's stance in a word and the line behind it"],
  ["Market", "breadth, movers by index and live prices every five minutes in market hours"],
  ["Watchlists and alerts", "a bell for new results and call transcripts on the stocks you watch"],
];
