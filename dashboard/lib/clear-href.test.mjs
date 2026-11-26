import assert from "node:assert/strict";
import { test } from "node:test";

import { clearedHref } from "./clear-href.mjs";

test("with nothing named, every param comes off", () => {
  assert.equal(clearedHref("/ind/screener", "?rating=BUY&sector=Energy&sort=pe"), "/ind/screener");
});

test("named params come off and the rest stay", () => {
  assert.equal(clearedHref("/ind/indices/nifty-50", "q=tcs&page=3&sort=pe&dir=asc", ["q", "page"]), "/ind/indices/nifty-50?sort=pe&dir=asc");
});

test("a URL left with nothing is the bare path", () => {
  assert.equal(clearedHref("/us/sectors/energy", "?q=xom", ["q", "page"]), "/us/sectors/energy");
});

test("accepts URLSearchParams and leaves them untouched", () => {
  const params = new URLSearchParams("q=a&density=compact");
  assert.equal(clearedHref("/ind/watchlists", params, ["q"]), "/ind/watchlists?density=compact");
  assert.equal(params.get("q"), "a");
});
