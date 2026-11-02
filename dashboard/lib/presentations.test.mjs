import assert from "node:assert/strict";
import test from "node:test";

import { presentationFor } from "./presentations.mjs";

const rows = [
  { announced_at: "2026-11-05T00:00:00Z", url: "late" },
  { announced_at: "2026-11-02T10:00:00Z", url: "near" },
  { announced_at: "2026-10-01T00:00:00Z", url: "old" },
];

test("takes the newest presentation within -1 to +7 days of the result", () => {
  assert.equal(presentationFor(rows, "2026-11-02T09:00:00Z"), "late");
});
test("none in the window, or no broadcast time, is no link", () => {
  assert.equal(presentationFor(rows, "2026-12-01T00:00:00Z"), null);
  assert.equal(presentationFor(rows, null), null);
  assert.equal(presentationFor(undefined, "2026-11-02T00:00:00Z"), null);
});
