/**
 * How long a stock has been where it is, for display beside the stage.
 *
 * Three different "how long" figures exist, and they disagree on purpose:
 *
 *   days_in_stage     the current *label* run. A pullback under the 50-day
 *                     average turns Stage 2 into S2 Candidate and back, and
 *                     each flip restarts it -- so a stock advancing since June
 *                     can read 0 the day it recovers.
 *   stage2_entry_date when this advance first reached the full Stage 2 stack.
 *   advance_age_days  the whole advance, Stage 2 and its pullbacks together.
 *
 * The grid shows days since Stage 2 entry, the same figure the stock page
 * gives as "Entered Stage 2", so the two screens answer "how long has this been
 * advancing?" with one number. The other two stay in the tooltip: one figure in
 * the column, all three a hover away.
 */

/** Mirrors `ADVANCING_STAGES` in screener/stage.py. */
export const ADVANCING_STAGES = ["Stage 2", "S2 Candidate"];

/** Whole calendar days between two ISO dates, as the stock page counts them. */
export function daysBetween(from, to) {
  return Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000);
}

export function stageAge(row) {
  if (row.stage && ADVANCING_STAGES.includes(row.stage)) {
    if (row.stage2_entry_date && row.price_bar_as_of) {
      return {
        days: daysBetween(row.stage2_entry_date, row.price_bar_as_of),
        // The advance was already under way when the price history begins, so
        // the entry date is an upper bound and the count a floor.
        censored: Boolean(row.stage2_entry_censored),
        basis: "stage2",
      };
    }
    // Advancing but never reached the full stack in the data: the advance's own
    // age is the only honest figure.
    if (row.advance_age_days !== null && row.advance_age_days !== undefined) {
      return {
        days: row.advance_age_days,
        censored: Boolean(row.advance_age_censored),
        basis: "advance",
      };
    }
  }
  if (row.days_in_stage === null || row.days_in_stage === undefined) {
    return null;
  }
  return { days: row.days_in_stage, censored: false, basis: "label" };
}
