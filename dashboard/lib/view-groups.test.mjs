import assert from "node:assert/strict";
import test from "node:test";

import { VIEW_GROUPS, groupViews, viewsButtonLabel } from "./view-groups.mjs";

test("views sit under their headings in the menu's order, empty headings left out", () => {
  const grouped = groupViews([
    { id: "size", group: "Size" },
    { id: "blend", group: "Score" },
    { id: "fii", group: "Ownership and flows" },
    { id: "stray", group: "Nowhere" },
  ]);
  assert.deepEqual(grouped.map((entry) => entry.group), ["Score", "Ownership and flows", "Size", "More"]);
  assert.deepEqual(grouped.at(-1)?.views.map((view) => view.id), ["stray"]);
});

test("every built-in view names a heading the menu has", async () => {
  // presets.ts is TypeScript; its group fields are read as text so the test needs no build.
  const { readFile } = await import("node:fs/promises");
  const source = await readFile(new URL("./presets.ts", import.meta.url), "utf8");
  const groups = [...source.matchAll(/group: "([^"]+)"/g)].map((match) => match[1]);
  const ids = [...source.matchAll(/\bid: "([^"]+)"/g)];
  assert.equal(groups.length, ids.length, "each preset has a group");
  for (const group of groups) assert.ok(VIEW_GROUPS.includes(group), group);
});

test("the button names the one view that is on, else says Views", () => {
  assert.equal(viewsButtonLabel([]), "Views");
  assert.equal(viewsButtonLabel(["Cupel blend"]), "Cupel blend");
  assert.equal(viewsButtonLabel(["Cupel blend", "Foreign tailwind"]), "Views");
});
