import assert from "node:assert/strict";
import test from "node:test";

import { liveFor, peerSlice, rebase, squarify, stockSectorSlug, withLiveChange } from "./sectors.mjs";

test("a stock's sector page: the published map decides, else the snapshot sector", () => {
  const symbols = { TDPOWERSYS: "capital-goods" };
  assert.equal(stockSectorSlug(symbols, "TDPOWERSYS", "Industrials"), "capital-goods");
  assert.equal(stockSectorSlug(symbols, "ODDCO.BO", "Industrials"), null);
  assert.equal(stockSectorSlug(null, "AAPL", "Technology"), "technology");
  assert.equal(stockSectorSlug(null, "AAPL", null), null);
});

test("rebase starts at zero on the first point in range", () => {
  const out = rebase(
    [
      { time: "2026-01-01", value: 50 },
      { time: "2026-02-01", value: 100 },
      { time: "2026-03-01", value: 150 },
    ],
    "2026-01-15",
  );
  assert.deepEqual(out, [
    { time: "2026-02-01", value: 0 },
    { time: "2026-03-01", value: 50 },
  ]);
  assert.deepEqual(rebase([{ time: "2026-01-01", value: 1 }], "2027-01-01"), []);
});

test("a treemap fills the box with areas in proportion and drops empty sizes", () => {
  const tiles = squarify(
    [{ id: "a", size: 6 }, { id: "b", size: 6 }, { id: "c", size: 4 }, { id: "d", size: 3 }, { id: "e", size: 0 }],
    6,
    4,
  );
  assert.equal(tiles.length, 4);
  const area = tiles.reduce((sum, tile) => sum + tile.w * tile.h, 0);
  assert.ok(Math.abs(area - 24) < 1e-9);
  const a = tiles.find((tile) => tile.id === "a");
  assert.ok(Math.abs(a.w * a.h - (6 / 19) * 24) < 1e-9);
  for (const tile of tiles) {
    assert.ok(tile.x >= -1e-9 && tile.y >= -1e-9 && tile.x + tile.w <= 6 + 1e-9 && tile.y + tile.h <= 4 + 1e-9);
  }
  assert.deepEqual(squarify([], 10, 10), []);
});

test("peerSlice keeps the largest members and the stock itself, with its place by market cap", () => {
  const members = [
    { s: "A", mc: 300 },
    { s: "B", mc: null },
    { s: "C", mc: 100 },
    { s: "D", mc: 200 },
  ];
  const top = peerSlice(members, "C", 2);
  assert.deepEqual(top.peers.map((m) => m.s), ["A", "D", "C"]);
  assert.equal(top.capRank, 3);
  assert.equal(top.ranked, 3);
  const unreported = peerSlice(members, "B", 2);
  assert.equal(unreported.capRank, null);
  assert.deepEqual(unreported.peers.map((m) => m.s), ["A", "D", "B"]);
  assert.equal(peerSlice(members, "Z", 5).own, null);
});

test("a live reading counts only from a later session than the close", () => {
  const live = { session: "2026-11-19", d1: 1.2 };
  assert.equal(liveFor("2026-11-18", live), live);
  assert.equal(liveFor("2026-11-19", live), null); // the evening run already holds this session
  assert.equal(liveFor("2026-11-18", null), null);
  assert.equal(liveFor(null, live), null);
});

test("withLiveChange takes a member's 1D from a later-session quote, else keeps the close's", () => {
  const members = [
    { s: "A", d1: -2.33 },
    { s: "B", d1: -1 },
    { s: "C", d1: 0.5 },
    { s: "D", d1: 3 },
  ];
  const quotes = {
    A: { session: "2026-11-20", change_pct: 1.67 },
    B: { session: "2026-11-19", change_pct: 9 }, // the close already holds this session
    C: { session: "2026-11-20", change_pct: null }, // withheld as a unit change
  };
  const out = withLiveChange(members, "2026-11-19", (s) => quotes[s] ?? null);
  assert.deepEqual(out.map((m) => m.d1), [1.67, -1, 0.5, 3]);
  assert.equal(members[0].d1, -2.33); // input untouched
});
