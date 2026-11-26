/**
 * The pages Cloudflare serves from the assets directory, without running the Worker:
 * every page under app/(static) that Next prerendered for good (no revalidate). An ISR
 * page (`/`, `/login`) is left out on purpose -- copied, it would never refresh.
 * scripts/static-pages.mjs copies their HTML after `opennextjs-cloudflare build`.
 */

export const STATIC_GROUP = "/(static)";

/**
 * @param {Record<string, string>} appPaths `.next/server/app-paths-manifest.json`
 * @param {{ routes?: Record<string, { srcRoute?: string | null, initialRevalidateSeconds?: number | false }> }} prerender `.next/prerender-manifest.json`
 * @returns {string[]} the URL paths, e.g. "/ind/flows"
 */
export function staticPages(appPaths, prerender) {
  const sources = new Set(
    Object.keys(appPaths)
      .filter((path) => path.startsWith(`${STATIC_GROUP}/`) && path.endsWith("/page"))
      .map((path) => path.slice(STATIC_GROUP.length, -"/page".length)),
  );
  return Object.entries(prerender.routes ?? {})
    .filter(([route, entry]) => sources.has(entry.srcRoute ?? route) && entry.initialRevalidateSeconds === false)
    .map(([route]) => route)
    .sort();
}

/*
 * A link to a static page is a client navigation only if the router gets the page's RSC
 * payload: it asks the page's own URL with an `rsc: 1` header, and Cloudflare's assets,
 * matching on the path alone, would answer with the HTML (the router then reloads the
 * document). So these pages are `run_worker_first` in the wrangler configs, and the
 * Worker (worker.mjs) answers from the files Next prerendered beside the HTML, as Next does:
 * `.rsc` for a navigation, the segment's file (`segmentFile`) for a segment prefetch, and an
 * empty 404 for a segment the build did not emit -- never the whole page, which the router
 * would not count as the segment and would ask for again.
 */

export const RSC_VARY = "RSC, Next-Router-State-Tree, Next-Router-Prefetch, Next-Router-Segment-Prefetch, Next-Url";

/**
 * The headers Next sends with a prerendered page's payload, from its `.meta` file; cache
 * tags are left out, since nothing revalidates a static page.
 * @param {{ headers?: Record<string, string> }} meta
 */
export function rscHeaders(meta) {
  const headers = { ...meta.headers };
  delete headers["x-next-cache-tags"];
  return headers;
}

/**
 * Which file answers a request for a static page.
 * @param {string} page the page's path, e.g. "/ind/flows"
 * @param {string | null} rsc the `rsc` request header
 * @param {string | null} segment the `next-router-segment-prefetch` request header
 * @returns {{ asset: string | null, segment: boolean } | null} null: the HTML; asset null: a 404
 */
export function rscAsset(page, rsc, segment) {
  if (rsc !== "1") return null;
  if (segment === null) return { asset: `${page}.rsc`, segment: false };
  const file = segmentFile(segment);
  return { asset: file && `${page}.segments/${file}`, segment: true };
}

/**
 * The flat file name a segment's payload is copied to. Next names them by the segment path
 * (`/!KHN0YXRpYyk/$d$market/flows/__PAGE__`), and the assets binding answered 404 for those
 * paths from the Worker though the edge served them (26 Nov 2026), so they are stored base64url.
 * @param {string} segment the `next-router-segment-prefetch` header, e.g. "/_tree"
 * @returns {string | null} null for a value that is no segment path
 */
export function segmentFile(segment) {
  if (!segment.startsWith("/") || !/^[\x21-\x7e]+$/.test(segment)) return null;
  return `${btoa(segment).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")}.rsc`;
}

/**
 * The static pages a wrangler config does not run the Worker first for; the build fails
 * on any, since their links would reload the document.
 * @param {string[]} pages
 * @param {string} config the config's text (JSONC)
 */
export function pagesNotWorkerFirst(pages, config) {
  const list = config.match(/"run_worker_first"\s*:\s*(\[[^\]]*\])/);
  const first = new Set(list ? JSON.parse(list[1]) : []);
  return pages.filter((page) => !first.has(page));
}
