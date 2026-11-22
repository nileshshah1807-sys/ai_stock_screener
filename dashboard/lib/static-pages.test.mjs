import assert from "node:assert/strict";
import test from "node:test";

import { staticPages } from "./static-pages.mjs";

const appPaths = {
  "/(static)/[market]/flows/page": "app/(static)/[market]/flows/page.js",
  "/(app)/[market]/(market)/breadth/page": "app/(app)/[market]/(market)/breadth/page.js",
  "/page": "app/page.js",
  "/api/objects/route": "app/api/objects/route.js",
};

test("only the static group's pages, prerendered for good, are served from assets", () => {
  const prerender = {
    routes: {
      "/us/flows": { srcRoute: "/[market]/flows", initialRevalidateSeconds: false },
      "/ind/flows": { srcRoute: "/[market]/flows", initialRevalidateSeconds: false },
      // ISR: copied, it would never refresh.
      "/": { srcRoute: null, initialRevalidateSeconds: 300 },
      "/ind/breadth": { srcRoute: "/[market]/breadth", initialRevalidateSeconds: false },
    },
  };
  assert.deepEqual(staticPages(appPaths, prerender), ["/ind/flows", "/us/flows"]);
});

test("a static page that revalidates, or nothing prerendered, gives nothing", () => {
  assert.deepEqual(staticPages(appPaths, { routes: { "/ind/flows": { srcRoute: "/[market]/flows", initialRevalidateSeconds: 60 } } }), []);
  assert.deepEqual(staticPages(appPaths, {}), []);
});

test("a static page with no dynamic segment is matched by its own route", () => {
  const paths = { "/(static)/status/page": "app/(static)/status/page.js" };
  assert.deepEqual(staticPages(paths, { routes: { "/status": { srcRoute: null, initialRevalidateSeconds: false } } }), ["/status"]);
});
