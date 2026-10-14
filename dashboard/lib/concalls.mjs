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
 * where the company's prospects stand: what management stated, weighed
 * against the difficulty it conceded. This is that answer -- a judgment with
 * a quote, not a count of words. (The page first labelled calls from the
 * word-list tone score, and called a wealth manager "Bearish" for discussing
 * market risk, which is its business; then asked for management's own view,
 * and every call was "Optimistic".)
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
 * What the stock page's "What management said" should read: the published
 * run's own fields, or a newer call's from the concall feed.
 *
 * The page reads a run, and the screener runs once a day. A call transcribed
 * this evening is read for its outlook within the hour, so until the next run
 * the panel would describe last quarter's call. When the feed has a call held
 * after the one the run scored, with an outlook to show, the panel reads that
 * call instead and says it is not in the score yet. Once a run scores it the
 * dates match and the panel is the run's again -- one panel throughout.
 *
 * The feed's detail carries the same field names a run publishes, so it is
 * laid over the run's. Two things stay the run's: the median it compares
 * against, and the fact that this call has not been applied.
 *
 * Dates compare as ISO strings; anything that is not a date -- the page's
 * dash for "none" included -- is no call, older than any.
 */
export function callPanelSource(payload, call) {
  const run = payload ?? {};
  const fromRun = { payload: run, pending: null };
  const isoDate = (value) => {
    const text = typeof value === "string" ? value.trim().slice(0, 10) : "";
    return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : "";
  };
  const held = isoDate(call?.call_date);
  const detail = call?.outlook_detail;
  if (!held || held <= isoDate(run.Transcript_Call_Date)) return fromRun;
  if (!detail || typeof detail !== "object" || number(detail.Transcript_Outlook_Score) === null) return fromRun;
  return {
    payload: {
      Transcript_Outlook_Neutral_Score: run.Transcript_Outlook_Neutral_Score,
      ...detail,
      Transcript_Outlook_Applied: false,
    },
    pending: {
      source: sourceLabel(call.source),
      stance: stanceLabel(call.management_stance, call.management_stance_quote),
    },
  };
}

/** The stances a call can be filtered by, in the order they are offered. */
export const STANCE_FILTERS = Object.entries(STANCES).map(([value, { label }]) => ({ value, label }));

/**
 * A search box's text, made safe to place inside a PostgREST `or=(...)`
 * filter: commas, brackets, quotes and wildcards are that filter's own
 * syntax, and a company name needs none of them. Capped, because the text
 * comes from a URL.
 */
export function searchTerm(value) {
  const first = Array.isArray(value) ? value[0] : value;
  if (typeof first !== "string") return "";
  return first
    .replace(/[^\p{L}\p{N}&.' -]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 60);
}
