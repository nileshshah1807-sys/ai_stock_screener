/**
 * Rows in the shape of the upcoming-events table, for developing the UI before
 * the table exists. Read only when UPCOMING_FIXTURES=1 (see lib/upcoming.ts);
 * the volumes follow the exchange's notices: results peak near 200 a day, and
 * about one call in four names no time.
 */
const RESULTS_PER_DAY = [53, 0, 0, 133, 179, 205, 213, 140, 60, 0, 0, 22, 9];
const CALLS_PER_DAY = [14, 0, 0, 96, 118, 104, 90, 61, 40, 0, 0, 12, 0];
const HOURS = [10, 11, 12, 14, 15, 16, 17];
const REAL = ["TCS", "RELIANCE", "INFY", "HDFCBANK", "ITC"];

const day = (today, offset) =>
  new Date(Date.parse(`${today}T00:00:00Z`) + offset * 86_400_000).toISOString().slice(0, 10);

export function fixtureEvents(today) {
  const rows = [];
  RESULTS_PER_DAY.forEach((count, offset) => {
    for (let i = 0; i < count; i += 1) {
      const symbol = offset === 4 && i < REAL.length ? REAL[i] : `RES${offset}X${String(i).padStart(3, "0")}`;
      rows.push({ kind: "results", symbol, company: `${symbol} Limited`, event_date: day(today, offset), event_time: null });
    }
  });
  CALLS_PER_DAY.forEach((count, offset) => {
    for (let i = 0; i < count; i += 1) {
      const symbol = `CALL${offset}X${String(i).padStart(3, "0")}`;
      const date = day(today, offset);
      const hour = HOURS[i % HOURS.length];
      const time = i % 4 === 3 ? null : `${date}T${String(hour).padStart(2, "0")}:${i % 2 ? "30" : "00"}:00+05:30`;
      rows.push({ kind: "call", symbol, company: `${symbol} Limited`, event_date: date, event_time: time });
    }
  });
  return rows;
}
