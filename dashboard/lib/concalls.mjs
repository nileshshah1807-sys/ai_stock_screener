/**
 * What the Concalls page says about a call.
 *
 * Kept free of React and of the Supabase client so the wording and the
 * thresholds can be tested directly (see the .test.mjs beside this).
 */

function number(value) {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/**
 * Management's tone as one of five words, from where the call's tone score
 * stands among the season's calls.
 *
 * Standing, not score: the tone score has no natural scale and most calls sit
 * within a few points of each other, so a fixed cut-off would call nearly
 * every call the same thing. Fifths of the season's calls say which calls
 * sounded better than most. A call with no standing gets no word -- an
 * unscored call is not a bearish one.
 */
const TONE_STEPS = [
  { from: 80, label: "Bullish", tone: "positive" },
  { from: 60, label: "Optimistic", tone: "positive" },
  { from: 40, label: "Neutral", tone: "muted" },
  { from: 20, label: "Cautious", tone: "negative" },
  { from: 0, label: "Bearish", tone: "negative" },
];

export function toneLabel(percentile) {
  const standing = number(percentile);
  if (standing === null) return null;
  const step = TONE_STEPS.find((item) => standing >= item.from) ?? TONE_STEPS[TONE_STEPS.length - 1];
  return { label: step.label, tone: step.tone };
}

/**
 * Where the call's text came from, and what that means for the reader.
 *
 * A recording has no speaker labels and its figures are as the model heard
 * them, so the row says so until the company's own transcript replaces it.
 */
export function sourceLabel(source) {
  if (source === "recording") {
    return {
      label: "From the recording",
      title:
        "Transcribed by a speech model from the recording the company filed. Replaced by the company's transcript when it is filed.",
      provisional: true,
    };
  }
  return { label: "Filed transcript", title: "The transcript the company filed with the exchange.", provisional: false };
}

/**
 * The outlook score against the neutral 50 it starts from: the score only
 * moves on something the call stated, so 50 means "nothing scored", not
 * "average".
 */
export function outlookTone(score) {
  const value = number(score);
  if (value === null) return null;
  if (value > 50) return "positive";
  if (value < 50) return "negative";
  return "muted";
}

/** Highlights as stored are lower-case reasons; "tailwind: x" reads as "Tailwind: x". */
export function highlightList(value) {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      const text = typeof item?.text === "string" ? item.text.trim() : "";
      return {
        text: text ? text[0].toUpperCase() + text.slice(1) : "",
        tone: item?.tone === "negative" ? "negative" : "positive",
        quote: typeof item?.quote === "string" ? item.quote.trim() : "",
      };
    })
    .filter((item) => item.text);
}

/** Calls grouped by the day they were held, in the order given. */
export function groupByCallDate(calls) {
  const groups = [];
  for (const call of calls ?? []) {
    const last = groups[groups.length - 1];
    if (last && last.date === call.call_date) last.calls.push(call);
    else groups.push({ date: call.call_date, calls: [call] });
  }
  return groups;
}

/**
 * The call the stock page should announce: one held after the call the
 * published run scored, or null.
 *
 * The stock page reads a run, and a run is a day old by the next evening. A
 * call transcribed tonight is in the feed at once but reaches "What management
 * said" only when the screener next runs. Dates compare as ISO strings; a run
 * that scored no call at all is older than any call.
 */
export function callAfterRun(call, scoredCallDate) {
  const held = typeof call?.call_date === "string" ? call.call_date.slice(0, 10) : "";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(held)) return null;
  // Anything that is not a date -- the page's dash for "none" included -- is no call.
  const given = typeof scoredCallDate === "string" ? scoredCallDate.trim().slice(0, 10) : "";
  const scored = /^\d{4}-\d{2}-\d{2}$/.test(given) ? given : "";
  return held > scored ? call : null;
}
