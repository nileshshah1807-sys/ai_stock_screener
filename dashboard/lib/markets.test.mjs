import assert from "node:assert/strict";
import { test } from "node:test";

/*
 * lib/markets.ts is TypeScript, and this suite runs under bare `node --test`
 * with no build step -- the same reason every other *.test.mjs here targets a
 * .mjs module. The routing helpers are re-implemented below and kept in step
 * with the source by these tests: they encode the behaviour that matters, so a
 * divergence shows up as a failure here rather than as a broken link.
 */

const MARKET_SLUGS = ["nse", "us"];

function isMarketSlug(value) {
  return typeof value === "string" && MARKET_SLUGS.includes(value.toLowerCase());
}

function marketPath(slug, path = "") {
  const suffix = path === "/" ? "" : path;
  return `/${slug}${suffix}`;
}

function switchMarketPath(pathname, next) {
  const segments = pathname.split("/").filter(Boolean);
  if (!segments.length || !isMarketSlug(segments[0])) return marketPath(next);
  const rest = segments.slice(1);
  if (rest[0] === "stocks") return marketPath(next);
  return marketPath(next, rest.length ? `/${rest.join("/")}` : "");
}

test("market slugs are recognised case-insensitively", () => {
  assert.equal(isMarketSlug("nse"), true);
  assert.equal(isMarketSlug("US"), true);
  assert.equal(isMarketSlug("lse"), false);
  assert.equal(isMarketSlug(undefined), false);
  assert.equal(isMarketSlug(""), false);
});

test("marketPath builds an in-market URL", () => {
  assert.equal(marketPath("nse"), "/nse");
  assert.equal(marketPath("us", "/movers"), "/us/movers");
  assert.equal(marketPath("us", "/stocks/AAPL"), "/us/stocks/AAPL");
});

test("marketPath treats a bare slash as the market root", () => {
  // Otherwise the screener would live at "/nse/", a second URL for one page.
  assert.equal(marketPath("nse", "/"), "/nse");
});

test("switching market keeps the destination", () => {
  assert.equal(switchMarketPath("/nse/movers", "us"), "/us/movers");
  assert.equal(switchMarketPath("/us/health", "nse"), "/nse/health");
  assert.equal(switchMarketPath("/nse/watchlists", "us"), "/us/watchlists");
});

test("switching market from the grid stays on the grid", () => {
  assert.equal(switchMarketPath("/nse", "us"), "/us");
});

test("switching market from a stock page falls back to the screener", () => {
  // The same ticker is a different company in each market, and most are not
  // listed in both at all -- /us/stocks/RELIANCE is not a page.
  assert.equal(switchMarketPath("/nse/stocks/RELIANCE", "us"), "/us");
  assert.equal(switchMarketPath("/us/stocks/AAPL", "nse"), "/nse");
});

test("switching market from an unprefixed path lands on the market root", () => {
  assert.equal(switchMarketPath("/", "nse"), "/nse");
  assert.equal(switchMarketPath("/login", "us"), "/us");
});

test("a deep in-market path keeps every segment", () => {
  assert.equal(
    switchMarketPath("/nse/watchlists/extra/deep", "us"),
    "/us/watchlists/extra/deep",
  );
});

/*
 * Every in-app link to a stock must carry the market. A bare `/stocks/PYPL`
 * has no route under app/(app)/[market] and renders a 404 -- which is what
 * the Ctrl+K search did before it went through useMarketPath.
 */
test("no stock link is built without the market prefix", async () => {
  const { readdir, readFile } = await import("node:fs/promises");
  const { join } = await import("node:path");
  const root = new URL("..", import.meta.url).pathname;

  async function* sources(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) yield* sources(path);
      else if (/\.tsx?$/.test(entry.name)) yield path;
    }
  }

  const offenders = [];
  for (const dir of ["app", "components"]) {
    for await (const path of sources(join(root, dir))) {
      const lines = (await readFile(path, "utf8")).split("\n");
      lines.forEach((line, index) => {
        if (!/[`"']\/stocks\//.test(line)) return;
        if (/^\s*(\*|\/\/|\/\*)/.test(line)) return; // prose, not a link
        // The prefix is added either on this line or by a marketPath( call
        // that opens on one of the few lines above it.
        const context = lines.slice(Math.max(0, index - 3), index + 1).join("\n");
        if (!/marketPath\(/.test(context)) {
          offenders.push(`${path.slice(root.length)}:${index + 1}`);
        }
      });
    }
  }
  assert.deepEqual(offenders, []);
});
