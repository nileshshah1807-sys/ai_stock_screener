import assert from "node:assert/strict";
import test from "node:test";

import { pagesNotWorkerFirst, rscAsset, rscHeaders, segmentFile, staticPages } from "./static-pages.mjs";

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

test("a static page's RSC request gets its payload, a segment prefetch its segment, anything else the HTML", () => {
  assert.equal(rscAsset("/ind/flows", null, null), null);
  assert.equal(rscAsset("/ind/flows", "0", null), null);
  assert.deepEqual(rscAsset("/ind/flows", "1", null), { asset: "/ind/flows.rsc", segment: false });
  assert.deepEqual(rscAsset("/ind/flows", "1", "/_tree"), { asset: "/ind/flows.segments/L190cmVl.rsc", segment: true });
  const page = rscAsset("/ind/flows", "1", "/!KHN0YXRpYyk/$d$market/flows/__PAGE__");
  assert.match(page.asset, /^\/ind\/flows\.segments\/[A-Za-z0-9_-]+\.rsc$/);
  assert.equal(atob(page.asset.slice("/ind/flows.segments/".length, -4).replace(/-/g, "+").replace(/_/g, "/")), "/!KHN0YXRpYyk/$d$market/flows/__PAGE__");
});

test("a segment file name is one flat name, so no header value can reach another file", () => {
  assert.doesNotMatch(segmentFile("/../../us/flows"), /\//);
  assert.equal(segmentFile("_tree"), null);
  assert.equal(segmentFile("/a b"), null);
  assert.equal(segmentFile("/\u00e9"), null);
  assert.deepEqual(rscAsset("/ind/flows", "1", "_tree"), { asset: null, segment: true });
});

test("the payload carries Next's prerender headers, not its cache tags", () => {
  const meta = { headers: { "x-nextjs-stale-time": "300", "x-nextjs-prerender": "1", "x-next-cache-tags": "_N_T_/layout" } };
  assert.deepEqual(rscHeaders(meta), { "x-nextjs-stale-time": "300", "x-nextjs-prerender": "1" });
  assert.deepEqual(rscHeaders({}), {});
});

test("a static page missing from a config's run_worker_first is named", () => {
  const config = `{\n  // assets\n  "assets": { "directory": ".open-next/assets", "run_worker_first": ["/ind/flows"] }\n}`;
  assert.deepEqual(pagesNotWorkerFirst(["/ind/flows", "/us/flows"], config), ["/us/flows"]);
  assert.deepEqual(pagesNotWorkerFirst(["/ind/flows"], `{ "assets": {} }`), ["/ind/flows"]);
});
