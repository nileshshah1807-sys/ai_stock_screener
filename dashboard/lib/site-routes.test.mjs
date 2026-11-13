import assert from "node:assert/strict";
import { readdirSync } from "node:fs";
import { test } from "node:test";

import { PRIVATE_SEGMENTS, PUBLIC_SEGMENTS, isKnownPath, isPrivatePath } from "./site-routes.mjs";

/** Top-level route segments under app/, route groups flattened; [market] is the market slugs. */
function topSegments(dir) {
  return readdirSync(dir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .flatMap((entry) => (entry.name.startsWith("(") ? topSegments(new URL(`${entry.name}/`, dir)) : [entry.name]));
}

test("every top-level route is classed public or private, so a new one cannot slip past sign-in", () => {
  for (const segment of topSegments(new URL("../app/", import.meta.url))) {
    if (segment === "[market]" || segment.startsWith("_")) continue;
    assert.ok(PRIVATE_SEGMENTS.includes(segment) || PUBLIC_SEGMENTS.includes(segment), `classify /${segment} in lib/site-routes.mjs`);
  }
});

test("only the app's own segments need a session; an unknown path does not", () => {
  for (const path of ["/ind", "/us/concalls", "/NSE", "/screener", "/account", "/api/export", "/admin/plans"]) assert.equal(isPrivatePath(path), true, path);
  for (const path of ["/", "/nope-xyz", "/favicon.ico", "/opengraph-image", "/pricing", "/login", "/users", "/industries"]) assert.equal(isPrivatePath(path), false, path);
});

test("an unknown first segment is not a route, so it can answer 404", () => {
  for (const path of ["/", "/pricing", "/robots.txt", "/opengraph-image", "/ind/concalls", "/auth/callback"]) assert.equal(isKnownPath(path), true, path);
  for (const path of ["/nope-xyz", "/wp-login.php", "/users"]) assert.equal(isKnownPath(path), false, path);
});
