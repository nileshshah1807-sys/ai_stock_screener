import assert from "node:assert/strict";
import { test } from "node:test";

import { groupByCallDate, highlightList, outlookTone, sourceLabel, toneLabel } from "./concalls.mjs";

test("tone is a word for each fifth of the season's calls", () => {
  assert.deepEqual(
    [95, 80, 79.99, 60, 45, 20, 19.9, 0].map((standing) => toneLabel(standing).label),
    ["Bullish", "Bullish", "Optimistic", "Optimistic", "Neutral", "Cautious", "Bearish", "Bearish"],
  );
  assert.equal(toneLabel("72.5").tone, "positive");
  assert.equal(toneLabel(10).tone, "negative");
});

test("an unscored call gets no word rather than the lowest one", () => {
  assert.equal(toneLabel(null), null);
  assert.equal(toneLabel(undefined), null);
  assert.equal(toneLabel(""), null);
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
