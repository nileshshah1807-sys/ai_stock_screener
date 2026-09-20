/**
 * How long a stock has been where it is, for display beside the stage.
 *
 * `days_in_stage` counts the current *label*. A pullback under the 50-day
 * average turns Stage 2 into S2 Candidate and back again, and each flip
 * restarts that counter -- so a stock advancing since April can read `S2 0d`
 * the day it recovers, which is the opposite of what the number is for.
 *
 * `advance_age_days` spans Stage 2 and S2 Candidate as one unbroken run, which
 * is what a stage screener reports as days in stage, so an advancing stock is
 * shown that instead. Both remain in the tooltip.
 */

/** Mirrors `ADVANCING_STAGES` in screener/stage.py. */
export const ADVANCING_STAGES = ["Stage 2", "S2 Candidate"];

export function stageAge(row) {
  if (row.stage && ADVANCING_STAGES.includes(row.stage)) {
    if (row.advance_age_days !== null && row.advance_age_days !== undefined) {
      return {
        days: row.advance_age_days,
        // The screener flags an advance that was already running when its
        // price history begins: the age is then a floor, not a measurement.
        censored: Boolean(row.advance_age_censored),
      };
    }
  }
  if (row.days_in_stage === null || row.days_in_stage === undefined) {
    return null;
  }
  return { days: row.days_in_stage, censored: false };
}
