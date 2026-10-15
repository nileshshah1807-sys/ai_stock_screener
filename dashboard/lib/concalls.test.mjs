import assert from "node:assert/strict";
import { test } from "node:test";

import {
  STANCE_FILTERS,
  callPanelSource,
  groupByCallDate,
  highlightList,
  outlookTone,
  searchTerm,
  sourceLabel,
  stanceLabel,
} from "./concalls.mjs";

test("management's stance is the outlook score's band, with its sentence", () => {
  assert.deepEqual(stanceLabel("optimistic", " We expect a strong second half. "), {
    label: "Optimistic",
    tone: "positive",
    quote: "We expect a strong second half.",
  });
  assert.equal(stanceLabel("Bearish", null).tone, "negative");
  assert.equal(stanceLabel("neutral").tone, "muted");
  assert.equal(stanceLabel("cautious").quote, "");
});

test("a call with no stance gets no word rather than a neutral one", () => {
  assert.equal(stanceLabel(null), null);
  assert.equal(stanceLabel(""), null);
  assert.equal(stanceLabel("unknown"), null);
  assert.equal(stanceLabel("elated"), null);
});

test("a call read from its recording says so", () => {
  assert.equal(sourceLabel("recording").provisional, true);
  assert.equal(sourceLabel("recording").label, "From the recording");
  assert.equal(sourceLabel("transcript").provisional, false);
  // An unknown source is not presented as provisional.
  assert.equal(sourceLabel(undefined).label, "Filed transcript");
});

test("the outlook is read against the neutral 50", () => {
  assert.equal(outlookTone(68), "positive");
  assert.equal(outlookTone("41.5"), "negative");
  assert.equal(outlookTone(50), "muted");
  assert.equal(outlookTone(null), null);
});

test("highlights are sentence-cased and malformed ones dropped", () => {
  assert.deepEqual(
    highlightList([
      { text: "guidance raised", tone: "positive", quote: " We now expect more. " },
      { text: "tailwind: lower freight", tone: "negative" },
      { text: "  " },
      null,
    ]),
    [
      { text: "Guidance raised", tone: "positive", quote: "We now expect more." },
      { text: "Tailwind: lower freight", tone: "negative", quote: "" },
    ],
  );
  assert.deepEqual(highlightList("not a list"), []);
});

test("calls are grouped by the day they were held", () => {
  const groups = groupByCallDate([
    { symbol: "A", call_date: "2026-10-12" },
    { symbol: "B", call_date: "2026-10-12" },
    { symbol: "C", call_date: "2026-10-10" },
  ]);
  assert.deepEqual(
    groups.map((group) => [group.date, group.calls.length]),
    [["2026-10-12", 2], ["2026-10-10", 1]],
  );
  assert.deepEqual(groupByCallDate(null), []);
});

const RUN = {
  Transcript_Call_Date: "2026-07-15",
  Transcript_Outlook_Score: 53,
  Transcript_Outlook_Neutral_Score: 66,
  Transcript_Outlook_Applied: true,
};
const NEWER = {
  call_date: "2026-10-12",
  source: "recording",
  management_stance: "optimistic",
  outlook_detail: {
    Transcript_Call_Date: "2026-10-12",
    Transcript_Outlook_Score: 67,
    Transcript_Outlook_Previous_Score: 53,
  },
};

test("a call held after the one the run scored takes the panel, marked as not applied", () => {
  const { payload, pending } = callPanelSource(RUN, NEWER);
  assert.equal(payload.Transcript_Call_Date, "2026-10-12");
  assert.equal(payload.Transcript_Outlook_Score, 67);
  assert.equal(payload.Transcript_Outlook_Previous_Score, 53);
  // The run's median still applies; its "applied" does not.
  assert.equal(payload.Transcript_Outlook_Neutral_Score, 66);
  assert.equal(payload.Transcript_Outlook_Applied, false);
  assert.equal(pending.source.label, "From the recording");
  assert.equal(pending.stance.label, "Optimistic");
});

test("the panel is the run's own once the run has the call, or when there is nothing newer to show", () => {
  const same = { payload: RUN, pending: null };
  assert.deepEqual(callPanelSource({ ...RUN, Transcript_Call_Date: "2026-10-12" }, NEWER), {
    payload: { ...RUN, Transcript_Call_Date: "2026-10-12" },
    pending: null,
  });
  // The run scored the transcript filed days after the call.
  assert.equal(callPanelSource({ ...RUN, Transcript_Call_Date: "2026-10-16" }, NEWER).pending, null);
  assert.deepEqual(callPanelSource(RUN, null), same);
  // A newer call not yet read for its outlook has nothing to put in the panel.
  assert.deepEqual(callPanelSource(RUN, { ...NEWER, outlook_detail: null }), same);
  assert.deepEqual(callPanelSource(RUN, { ...NEWER, call_date: "soon" }), same);
});

test("a run that scored no call is older than any call", () => {
  for (const date of ["", undefined, "\u2014"]) {
    assert.equal(callPanelSource({ Transcript_Call_Date: date }, NEWER).payload.Transcript_Outlook_Score, 67);
  }
  assert.equal(callPanelSource(null, NEWER).pending.source.provisional, true);
});

test("a search is reduced to what a company name can contain", () => {
  assert.equal(searchTerm("  anand   rathi "), "anand rathi");
  assert.equal(searchTerm("M&M"), "M&M");
  // PostgREST filter syntax and wildcards never reach the query.
  assert.equal(searchTerm("a,symbol.eq.X)*%(\"b"), "a symbol.eq.X b");
  assert.equal(searchTerm(["tcs", "infy"]), "tcs");
  assert.equal(searchTerm(undefined), "");
  assert.equal(searchTerm("x".repeat(200)).length, 60);
});

test("the stance filter offers the five stances, best first", () => {
  assert.deepEqual(
    STANCE_FILTERS.map((item) => item.value),
    ["bullish", "optimistic", "neutral", "cautious", "bearish"],
  );
});
