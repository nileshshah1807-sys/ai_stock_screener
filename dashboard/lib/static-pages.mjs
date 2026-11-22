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
