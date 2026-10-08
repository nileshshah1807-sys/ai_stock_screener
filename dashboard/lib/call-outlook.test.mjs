import assert from "node:assert/strict";
import test from "node:test";

import { callOutlook, followThrough } from "./call-outlook.mjs";

const PAYLOAD = {
  Transcript_Call_Date: "2026-08-04",
  Transcript_Outlook_Score: 73,
  Transcript_Outlook_Neutral_Score: 66,
  Transcript_Outlook_Applied: true,
  Transcript_Outlook_Points: JSON.stringify([
    { reason: "guidance maintained", points: 3 },
    { reason: "headwind: input costs", points: -3 },
    { reason: "guided revenue growth 25% or more", points: 10 },
    { reason: "margin outlook flat", points: 0 },
  ]),
  Transcript_Outlook_Previous_Call_Date: "2026-05-12",
  Transcript_Outlook_Previous_Score: 81,
  Transcript_Outlook_QoQ_Delta: -8,
  Transcript_Outlook_QoQ_Items: JSON.stringify([
    { item: "demand", change: "kept", text: "demand outlook still strong" },
    { item: "margin", change: "better", text: "margin outlook down -> flat" },
    { item: "guidance", change: "worse", text: "guided growth cut 20% -> 15%" },
  ]),
};

test("a row without an outlook gives nothing to render", () => {
  assert.equal(callOutlook({}), null);
  assert.equal(callOutlook(null), null);
  assert.equal(callOutlook({ Transcript_Outlook_Score: null }), null);
  // An empty cell in an older run's payload must not read as a score of zero.
  assert.equal(callOutlook({ Transcript_Outlook_Score: "" }), null);
});

test("scored items are listed largest first and unscored ones dropped", () => {
  const outlook = callOutlook(PAYLOAD);
  assert.equal(outlook.score, 73);
  assert.equal(outlook.median, 66);
  assert.equal(outlook.applied, true);
  assert.deepEqual(outlook.points, [
    { reason: "Guided revenue growth 25% or more", points: 10, quote: "" },
    { reason: "Guidance maintained", points: 3, quote: "" },
    { reason: "Headwind: input costs", points: -3, quote: "" },
  ]);
});

test("items read off one sentence share a row and its quote", () => {
  const guidance = "We expect revenue of INR1,550 crores to INR1,650 crores.";
  const outlook = callOutlook({
    Transcript_Outlook_Score: 77,
    Transcript_Outlook_Points: JSON.stringify([
      { reason: "guidance maintained", points: 3, quote: guidance },
      { reason: "guided revenue growth 25% or more", points: 10, quote: guidance },
      { reason: "demand outlook strong", points: 8, quote: "Demand remains healthy." },
      { reason: "capacity planned", points: 1, quote: "" },
      { reason: "headwind: freight costs", points: -3, quote: "" },
    ]),
  });
  assert.deepEqual(outlook.points, [
    {
      reason: "Guidance maintained · guided revenue growth 25% or more",
      points: 13,
      quote: guidance,
    },
    { reason: "Demand outlook strong", points: 8, quote: "Demand remains healthy." },
    // No quote is not a shared quote: these stay separate.
    { reason: "Headwind: freight costs", points: -3, quote: "" },
    { reason: "Capacity planned", points: 1, quote: "" },
  ]);
});

test("changes since the previous call lead with what got worse", () => {
  const { previous } = callOutlook(PAYLOAD);
  assert.equal(previous.callDate, "2026-05-12");
  assert.equal(previous.delta, -8);
  assert.deepEqual(
    previous.changes.map((item) => item.change),
    ["worse", "better", "kept"],
  );
  assert.equal(previous.changes[0].text, "Guided growth cut 20% → 15%");
  assert.deepEqual([previous.kept, previous.better, previous.worse], [1, 1, 1]);
});

test("a commissioning month is written as a month, not as a number", () => {
  const { previous } = callOutlook({
    Transcript_Outlook_Score: 60,
    Transcript_Outlook_Previous_Score: 62,
    Transcript_Outlook_QoQ_Items: JSON.stringify([
      { change: "worse", text: "commissioning slipped 2026-12 -> 2027-03" },
      { change: "kept", text: "order book steady, 1,000 -> 1,020 crore" },
    ]),
  });
  assert.equal(previous.changes[0].text, "Commissioning slipped Dec 2026 → Mar 2027");
  assert.equal(previous.changes[1].text, "Order book steady, 1,000 → 1,020 crore");
});

test("a first call has no previous one to compare with", () => {
  const outlook = callOutlook({ Transcript_Outlook_Score: "58.0", Transcript_Outlook_Points: "[]" });
  assert.equal(outlook.score, 58);
  assert.equal(outlook.previous, null);
  assert.deepEqual(outlook.points, []);
  assert.equal(followThrough(outlook.previous), null);
});

test("malformed breakdowns degrade to an empty list, not a crash", () => {
  const outlook = callOutlook({
    Transcript_Outlook_Score: 60,
    Transcript_Outlook_Points: "{not json",
    Transcript_Outlook_Previous_Score: 55,
    Transcript_Outlook_QoQ_Items: JSON.stringify([{ change: "sideways", text: "x" }, null]),
  });
  assert.deepEqual(outlook.points, []);
  assert.deepEqual(outlook.previous.changes, []);
  assert.equal(outlook.previous.delta, 5);
});

test("follow-through is worded by whether anything slipped", () => {
  const base = { kept: 0, better: 0, worse: 0 };
  assert.deepEqual(followThrough({ ...base, kept: 2, better: 1, worse: 1 }), {
    tone: "negative",
    label: "1 of 4 items weaker than the previous call",
  });
  assert.deepEqual(followThrough({ ...base, kept: 2, better: 1 }), {
    tone: "positive",
    label: "Kept to the previous call and improved on 1 of 3 items",
  });
  assert.deepEqual(followThrough({ ...base, kept: 3 }), {
    tone: "default",
    label: "Kept to the previous call on all 3 items",
  });
  assert.equal(followThrough(base).tone, "muted");
});
