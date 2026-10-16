import assert from "node:assert/strict";
import test from "node:test";

import { indexSlug, rankIndices } from "./indices.mjs";

const NSE = [
  "Nifty 50",
  "Nifty Next 50",
  "Nifty Bank",
  "Nifty Midcap 150",
  "Nifty Smallcap 250",
  "Nifty Microcap 250",
  "Nifty 500",
].map((name) => ({ name }));

const names = (term, list = NSE) => rankIndices(list, term).map((index) => index.name);

test("a slug is the label in lower case, with no punctuation", () => {
  assert.equal(indexSlug("Nifty Smallcap 250"), "nifty-smallcap-250");
  assert.equal(indexSlug("Nifty 50"), "nifty-50");
  assert.equal(indexSlug("S&P 500"), "sp-500");
  assert.equal(indexSlug("Dow Jones Industrial"), "dow-jones-industrial");
});

test("every NSE slug is distinct", () => {
  const slugs = NSE.map((index) => indexSlug(index.name));
  assert.equal(new Set(slugs).size, slugs.length);
});

test("a prefix lists the market's indices in its own order", () => {
  assert.deepEqual(names("nif"), NSE.map((index) => index.name));
});

test("a word inside the label finds the index", () => {
  assert.deepEqual(names("smallcap"), ["Nifty Smallcap 250"]);
  assert.deepEqual(names("bank"), ["Nifty Bank"]);
});

test("a trading code finds the index it names, first", () => {
  assert.equal(names("banknifty")[0], "Nifty Bank");
  assert.equal(names("spx", [{ name: "Nasdaq Composite" }, { name: "S&P 500" }])[0], "S&P 500");
});

test("an index is listed once, however many of its terms match", () => {
  const found = names("nifty");
  assert.equal(found.length, new Set(found).size);
  assert.equal(found[0], "Nifty 50");
});

test("no term, no results", () => {
  assert.deepEqual(names(""), []);
  assert.deepEqual(names("   "), []);
});
