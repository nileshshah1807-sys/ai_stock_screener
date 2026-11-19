import assert from "node:assert/strict";
import test from "node:test";

import { screenerIntro } from "./screener-intro.mjs";

test("each market names its own universe and both say how and when", () => {
  assert.match(screenerIntro("NSE"), /^NSE- and BSE-listed companies/);
  assert.match(screenerIntro("US"), /^S&P 1500 companies/);
  for (const code of ["NSE", "US"]) {
    const text = screenerIntro(code);
    for (const word of ["quality", "growth", "value", "momentum", "risk", "every evening"]) assert.ok(text.includes(word), `${code}: ${word}`);
    assert.doesNotMatch(text, /\b(buy|sell|rating|ratings|recommend)/i, "no ratings wording for non-admins");
  }
});

test("both markets name management guidance (each scores its calls)", () => {
  for (const code of ["NSE", "US"]) assert.ok(screenerIntro(code).includes("management guidance"), code);
});
