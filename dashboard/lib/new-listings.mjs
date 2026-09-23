/**
 * Why a recent listing has no rating yet, in plain words.
 *
 * The statuses come from workers/new_listings.py, which applies the screener's
 * own admission rules. The copy states the rule and the stock's position
 * against it, so "not rated" never reads as "the screener missed this".
 *
 * Sessions are the price source's count, not days since the listing date --
 * a company re-dated onto the NSE mainboard can have far less vendor history
 * than its listing date suggests, and the vendor's count is what the 60-session
 * rule sees. The copy says "sessions of price history" for that reason.
 */

/** Short chip label. */
export const STATUS_LABEL = {
  insufficient_history: "Building history",
  below_liquidity_floor: "Below liquidity floor",
  no_price_data: "Awaiting prices",
  pending_run: "Next run",
};

/**
 * One-sentence explanation. `formatTurnover` renders a rupee amount in the
 * market's convention (the caller owns formatting so this stays pure).
 */
export function statusDetail(row, formatTurnover) {
  const need = row.sessions_required;
  const have = row.sessions ?? 0;
  switch (row.status) {
    case "insufficient_history": {
      const left = Math.max(0, need - have);
      return (
        `${have} of the ${need} sessions of price history the model needs. ` +
        `It is rated automatically after about ${left} more trading ${left === 1 ? "day" : "days"}.`
      );
    }
    case "below_liquidity_floor":
      return (
        `Has enough history, but 20-day turnover of ${formatTurnover(row.median_turnover_20d)} a day ` +
        `is under the ${formatTurnover(row.turnover_floor)} floor the screener requires to rate a stock.`
      );
    case "no_price_data":
      return "The price source has no trading history for this symbol yet.";
    case "pending_run":
      return "Meets the history and turnover minimums; it should be rated in an upcoming run.";
    default:
      return "Not rated in the latest run.";
  }
}

/** Progress toward the session minimum, 0-1, for the history bar. */
export function historyProgress(row) {
  if (!row.sessions_required) return 0;
  return Math.max(0, Math.min(1, (row.sessions ?? 0) / row.sessions_required));
}
