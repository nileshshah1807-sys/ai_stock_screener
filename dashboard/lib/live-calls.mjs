/**
 * Pure helpers for the live call page: the cursor merge, the clock stamp, and
 * the sample call shown while the live_calls tables are not applied.
 */

/** Lines by seq, ascending; a line already held is kept once. */
export function mergeLines(held, incoming) {
  const bySeq = new Map(held.map((line) => [line.seq, line]));
  for (const line of incoming) if (line.seq != null) bySeq.set(line.seq, line);
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq);
}

/** "4:07" or "1:02:09" from seconds into the call. */
export function clock(seconds) {
  const whole = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const s = String(whole % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

const SCRIPT = [
  "Good evening, everyone, and welcome to the earnings call for the quarter ended September.",
  "With me today are our Managing Director, our Chief Financial Officer and the head of investor relations.",
  "Before we start, please note that today's discussion may contain forward-looking statements.",
  "Revenue for the quarter grew eleven percent year on year, led by our domestic business.",
  "Operating margin improved by about one hundred basis points over the same quarter last year.",
  "The order book stands at a record, and we have good visibility for the next four quarters.",
  "Input costs eased through the quarter, and we expect that benefit to continue into the second half.",
  "We commissioned the new line on schedule, and utilisation there is already above sixty percent.",
  "Capital expenditure for the year remains in line with the guidance we gave in May.",
  "Net debt came down again, and we are comfortable with where the balance sheet is.",
  "On demand, our distributors tell us secondary sales were healthy through the festive build-up.",
  "Export revenue was flat, as two large customers pushed deliveries into the next quarter.",
  "We do not see a structural issue there, and those shipments are scheduled for November.",
  "For the full year, we continue to expect revenue growth in the low double digits.",
  "We would like to open the floor for questions.",
  "Thank you. Could you talk about the pricing environment in the domestic business?",
  "Yes. We took a small price increase in July, and it has held without any loss of volume.",
  "And on the new capacity, how quickly can it contribute to margin?",
  "We expect it to be margin accretive from the third quarter, once utilisation crosses seventy percent.",
  "Thank you. That is all from me.",
];

const SAMPLE_GAP_SECONDS = 5;

/**
 * Lines a sample call would have spoken `elapsed` seconds in, one every five
 * seconds, after `afterSeq`. The script repeats once it runs out.
 * shortcut: a loop of twenty lines, only for previews without the tables.
 */
export function sampleLines(elapsed, afterSeq = 0) {
  const spoken = Math.floor(elapsed / SAMPLE_GAP_SECONDS) + 1;
  const lines = [];
  for (let seq = afterSeq + 1; seq <= spoken; seq += 1) {
    lines.push({ seq, start_seconds: (seq - 1) * SAMPLE_GAP_SECONDS, text: SCRIPT[(seq - 1) % SCRIPT.length] });
  }
  return lines;
}
