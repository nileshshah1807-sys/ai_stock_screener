import assert from "node:assert/strict";
import test from "node:test";

import { viewIsActive } from "./view-match.mjs";

const FRESH_STAGE_2 =
  "minScore=70&stage=Stage+2&minRs=70&sort=advance_age_days&dir=asc";
const ACTIONABLE_BUY =
  "rating=STRONG+BUY&rating=BUY&buyEligible=1&actionable=1&sort=final_score&dir=desc";

const url = (query) => new URLSearchParams(query);

test("a view is active when the URL is exactly it", () => {
  assert.equal(viewIsActive(url(FRESH_STAGE_2), FRESH_STAGE_2), true);
});

test("narrowing a view keeps it active", () => {
  // The reported bug: picking the view and then the STRONG BUY pill left only
  // the pill lit, while the view's filters were plainly still applied.
  assert.equal(
    viewIsActive(url(`${FRESH_STAGE_2}&rating=STRONG+BUY`), FRESH_STAGE_2),
    true,
  );
  assert.equal(
    viewIsActive(url(`${FRESH_STAGE_2}&sector=Financials`), FRESH_STAGE_2),
    true,
  );
});

test("removing or changing one of the view's own filters deactivates it", () => {
  assert.equal(
    viewIsActive(url("minScore=70&stage=Stage+2&sort=advance_age_days&dir=asc"), FRESH_STAGE_2),
    false,
    "minRs dropped",
  );
  assert.equal(
    viewIsActive(url(FRESH_STAGE_2.replace("minScore=70", "minScore=60")), FRESH_STAGE_2),
    false,
    "minScore changed",
  );
  assert.equal(
    viewIsActive(url(FRESH_STAGE_2.replace("dir=asc", "dir=desc")), FRESH_STAGE_2),
    false,
    "sort direction flipped",
  );
});

test("order of repeated keys does not matter", () => {
  const reversed =
    "rating=BUY&rating=STRONG+BUY&buyEligible=1&actionable=1&sort=final_score&dir=desc";
  assert.equal(viewIsActive(url(reversed), ACTIONABLE_BUY), true);
});

test("a view wanting two ratings is not satisfied by one", () => {
  assert.equal(
    viewIsActive(
      url("rating=BUY&buyEligible=1&actionable=1&sort=final_score&dir=desc"),
      ACTIONABLE_BUY,
    ),
    false,
  );
});

test("page number is ignored", () => {
  assert.equal(viewIsActive(url(`${FRESH_STAGE_2}&page=7`), FRESH_STAGE_2), true);
});

test("an empty view is never active", () => {
  assert.equal(viewIsActive(url(FRESH_STAGE_2), ""), false);
  assert.equal(viewIsActive(url(""), ""), false);
});

test("a size floor is part of the view it belongs to", () => {
  assert.equal(viewIsActive(url("minCapCr=1000&rating=BUY"), "minCapCr=1000"), true);
  assert.equal(viewIsActive(url("minCapCr=500"), "minCapCr=1000"), false);
});

test("a view can be just a score mix, and lights only for that mix", () => {
  const view = "w=q25.g25.m30.v15.r5.d10.c100";
  assert.ok(viewIsActive(new URLSearchParams(`${view}&page=2`), view));
  assert.ok(!viewIsActive(new URLSearchParams("w=q20.g20.m20.v20.r20"), view));
});

test("applying a view keeps the filters already on", async () => {
  const { applyView, removeView } = await import("./view-match.mjs");
  const current = url("w=q50.m50&sector=Energy&page=3");
  const next = applyView(current, "cap=1000~");
  assert.equal(next.get("w"), "q50.m50");
  assert.equal(next.get("sector"), "Energy");
  assert.equal(next.get("cap"), "1000~");
  assert.equal(next.has("page"), false);
  assert.equal(viewIsActive(next, "cap=1000~"), true);
  // Taking it off again leaves what was there before.
  const back = removeView(next, "cap=1000~");
  assert.equal(back.toString(), "w=q50.m50&sector=Energy");
});

test("a view replaces the values of a key it sets", async () => {
  const { applyView } = await import("./view-match.mjs");
  assert.equal(applyView(url("cap=~500"), "cap=1000~").getAll("cap").join(), "1000~");
});

test("a saved view that carries presets lights alone, not the presets inside it", async () => {
  // The reported bug: GOAT was saved with Cupel blend and the size floor on,
  // so selecting it ticked all three.
  const { litViews } = await import("./view-match.mjs");
  const blend = { id: "cupel-blend", query: "sort=custom_score&w=q25.g25.m30.v15.r5.c50" };
  const floor = { id: "above-1000-cr", query: "cap=1000~" };
  const goat = { id: "goat", query: `${blend.query}&cap=1000~&density=compact` };
  const views = [blend, floor, goat];
  const ids = (query) => litViews(url(query), views).map((view) => view.id);

  assert.deepEqual(ids(goat.query), ["goat"]);
  assert.deepEqual(ids(`${goat.query}&sector=Energy`), ["goat"], "narrowing keeps it lit");
  // Without the saved view's own extra, the two presets are what is on.
  assert.deepEqual(ids(`${blend.query}&cap=1000~`), ["cupel-blend", "above-1000-cr"]);
  assert.deepEqual(ids("cap=1000~"), ["above-1000-cr"]);
  assert.deepEqual(ids(""), []);
});

test("two views with the same filters both light", async () => {
  const { litViews } = await import("./view-match.mjs");
  const a = { id: "a", query: "cap=1000~" };
  const b = { id: "b", query: "cap=1000~" };
  assert.deepEqual(litViews(url("cap=1000~"), [a, b]).map((view) => view.id), ["a", "b"]);
});
