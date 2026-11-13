/**
 * The app's top-level segments that need a session: the markets, the screener,
 * the account and admin pages, the API. The proxy sends a visitor without one
 * to sign in only for these.
 */
export const PRIVATE_SEGMENTS = ["ind", "us", "nse", "screener", "account", "admin", "admin-plans-preview", "billing-preview", "no-access", "api"];

/** Top-level segments anyone may open: the home page, the public pages and the files crawlers fetch. */
export const PUBLIC_SEGMENTS = ["", "pricing", "help", "terms", "privacy", "refunds", "disclaimer", "login", "auth", "robots.txt", "sitemap.xml", "opengraph-image", "favicon.ico", "icon.svg"];

const first = (pathname) => (pathname.split("/")[1] ?? "").toLowerCase();

/** @param {string} pathname */
export function isPrivatePath(pathname) {
  return PRIVATE_SEGMENTS.includes(first(pathname));
}

/**
 * Whether the app has a route at this path's first segment. `[market]` matches
 * any single segment, so without this an unknown URL (/nope) reached the app's
 * access check and answered with a sign-in redirect, not a 404.
 *
 * @param {string} pathname
 */
export function isKnownPath(pathname) {
  return isPrivatePath(pathname) || PUBLIC_SEGMENTS.includes(first(pathname));
}
