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
 * Management's stance as the outlook step read it, with the sentence behind it.
 *
 * A language model reads the whole call for its outlook and is asked, last,
 * how management itself sees what is ahead. This is that answer -- a judgment
 * with a quote, not a count of words. (The page first labelled calls from the
 * word-list tone score, and called a wealth manager "Bearish" for discussing
 * market risk, which is its business.)
 *
 * Null for a call read before the question was asked or one the model could
 * not place: no stance is not a neutral one.
 */
const STANCES = {
  bullish: { label: "Bullish", tone: "positive" },
  optimistic: { label: "Optimistic", tone: "positive" },
  neutral: { label: "Neutral", tone: "muted" },
  cautious: { label: "Cautious", tone: "negative" },
  bearish: { label: "Bearish", tone: "negative" },
};

export function stanceLabel(stance, quote) {
  const known = typeof stance === "string" ? STANCES[stance.trim().toLowerCase()] : undefined;
  if (!known) return null;
  return { ...known, quote: typeof quote === "string" ? quote.trim() : "" };
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
