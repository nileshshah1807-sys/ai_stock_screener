import assert from "node:assert/strict";
import test from "node:test";

import { groupDocuments } from "./documents.mjs";

const row = (kind, announced_at, extra = {}) => ({ kind, announced_at, title: `${kind} ${announced_at}`, url: `https://x/${kind}/${announced_at}`, ...extra });

test("groups in the fixed order, newest first, empty kinds left out", () => {
  const groups = groupDocuments([
    row("rating", "2026-01-01"),
    row("presentation", "2026-02-01"),
    row("presentation", "2026-05-01"),
  ]);
  assert.deepEqual(groups.map((g) => g.kind), ["presentation", "rating"]);
  assert.deepEqual(groups[0].items.map((i) => i.date), ["2026-05-01", "2026-02-01"]);
});

test("a transcript pairs with the recording just before it; others stay apart", () => {
  const [group] = groupDocuments([
    row("transcript", "2026-08-10T10:00:00Z"),
    row("recording", "2026-08-02T10:00:00Z"),
    row("recording", "2026-05-02T10:00:00Z"),
    row("transcript", "2026-01-02T10:00:00Z"),
  ]);
  assert.equal(group.kind, "concall");
  assert.equal(group.items.length, 3);
  assert.equal(group.items[0].title, "Earnings call");
  assert.deepEqual(group.items[0].links.map((l) => l.label), ["Transcript", "Recording"]);
  assert.equal(group.items[0].date, "2026-08-10T10:00:00Z");
});

test("rows without a link or a date are dropped; nothing gives no groups", () => {
  assert.deepEqual(groupDocuments([{ kind: "rating", announced_at: null, url: "u" }, { kind: "rating", announced_at: "2026-01-01" }]), []);
  assert.deepEqual(groupDocuments(null), []);
});
