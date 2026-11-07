import assert from "node:assert/strict";
import test from "node:test";

import { screenerIntro } from "./screener-intro.mjs";

test("each market names its own universe and both say how and when", () => {
  assert.match(screenerIntro("NSE"), /^NSE- and BSE-listed companies/);
  assert.match(screenerIntro("US"), /^NYSE- and Nasdaq-listed companies/);
  for (const code of ["NSE", "US"]) {
    const text = screenerIntro(code);
    for (const word of ["quality", "growth", "value", "momentum", "risk", "management guidance", "every evening"]) assert.ok(text.includes(word), `${code}: ${word}`);
    assert.doesNotMatch(text, /\b(buy|sell|rating|ratings|recommend)/i, "no ratings wording for non-admins");
  }
});
