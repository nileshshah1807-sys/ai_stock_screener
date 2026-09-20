import assert from "node:assert/strict";
import test from "node:test";

import { initials, rank, squash } from "./search.mjs";

/** A slice of the real universe: the awkward tickers plus ordinary ones. */
const UNIVERSE = [
  { s: "PGHH", c: "Procter & Gamble Hygiene and Health Care Limited", r: 300 },
  { s: "M&M", c: "Mahindra & Mahindra Limited", r: 10 },
  { s: "M&MFIN", c: "Mahindra & Mahindra Financial Services Limited", r: 40 },
  { s: "J&KBANK", c: "The Jammu & Kashmir Bank Limited", r: 80 },
  { s: "ARE&M", c: "Amara Raja Energy & Mobility Limited", r: 120 },
  { s: "BAJAJ-AUTO", c: "Bajaj Auto Limited", r: 12 },
  { s: "NAM-INDIA", c: "Nippon Life India Asset Management Limited", r: 220 },
  { s: "INFY", c: "Infosys Limited", r: 5 },
  { s: "INFIBEAM", c: "Infibeam Avenues Limited", r: 900 },
  { s: "TCS", c: "Tata Consultancy Services Limited", r: 3 },
  { s: "ARVIND", c: "Arvind Limited", r: 158 },
];

const top = (term) => rank(UNIVERSE, term).map((entry) => entry.s);

test("exact and prefix ticker matches still win", () => {
  assert.equal(top("INFY")[0], "INFY");
  assert.equal(top("TCS")[0], "TCS");
  // "INF" must reach INFY before INFIBEAM: tier is equal, rank decides.
  assert.deepEqual(top("INF").slice(0, 2), ["INFY", "INFIBEAM"]);
});

test("a company name finds its ticker", () => {
  assert.equal(top("mahindra")[0], "M&M");
  assert.equal(top("arvind")[0], "ARVIND");
});

test("an ampersand ticker is found with or without the ampersand", () => {
  for (const term of ["M&M", "m&m", "mm", "MM"]) {
    assert.equal(top(term)[0], "M&M", `term ${term}`);
  }
  assert.equal(top("j&k")[0], "J&KBANK");
  assert.equal(top("jk")[0], "J&KBANK");
  assert.equal(top("are&m")[0], "ARE&M");
});

test("a hyphenated ticker is found with a space or nothing in between", () => {
  for (const term of ["bajaj-auto", "bajaj auto", "bajajauto", "BAJAJAUTO"]) {
    assert.equal(top(term)[0], "BAJAJ-AUTO", `term ${term}`);
  }
});

test("an acronym finds a company whose ticker looks nothing like it", () => {
  // The reported bug: neither "PGHH" nor "Procter & Gamble Hygiene and Health
  // Care" contains the string "P&G", so substring matching alone found nothing.
  for (const term of ["p&g", "P&G", "pg"]) {
    assert.equal(top(term)[0], "PGHH", `term ${term}`);
  }
});

test("a punctuation-only query does not match on initials", () => {
  // "&" should reach only the tickers that literally contain it, never every
  // company by way of an empty squashed query.
  for (const symbol of rank(UNIVERSE, "&")) {
    assert.ok(symbol.s.includes("&") || symbol.c.includes("&"));
  }
  assert.deepEqual(rank(UNIVERSE, "   "), []);
});

test("a long query does not match loosely on initials", () => {
  // Six or more characters is a name, not an abbreviation.
  assert.equal(top("pghhcl").length, 0);
});

test("helpers", () => {
  assert.equal(squash("M&M"), "MM");
  assert.equal(squash("bajaj-auto"), "BAJAJAUTO");
  // Filler words are skipped, so an abbreviation people actually use lines up.
  assert.equal(initials("Procter & Gamble Hygiene and Health Care"), "PGHHC");
  assert.equal(initials("Bajaj Auto Limited"), "BA");
  assert.equal(initials("The Jammu & Kashmir Bank Limited"), "JKB");
});
