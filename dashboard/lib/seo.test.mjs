import assert from "node:assert/strict";
import test from "node:test";

import { APP_PATHS, PUBLIC_PATHS, faqJsonLd } from "./seo.mjs";

test("FAQ JSON-LD carries every question and answer, and cannot close its script tag", () => {
  const pairs = [["Is it free?", "7 days, then paid."], ["What </script> is this?", "<b>text</b>"]];
  const raw = faqJsonLd(pairs);
  assert.ok(!raw.includes("<"), "no raw angle bracket");
  const json = JSON.parse(raw);
  assert.equal(json["@type"], "FAQPage");
  assert.deepEqual(json.mainEntity.map((q) => [q.name, q.acceptedAnswer.text]), pairs);
});

test("public and app paths do not overlap", () => {
  for (const p of PUBLIC_PATHS) assert.ok(!APP_PATHS.some((a) => p === a || p.startsWith(a)), p);
});
