/*
 * The Worker's entry (`main` in wrangler.jsonc and wrangler.preview.jsonc), around the one
 * OpenNext builds. `/api/objects` -- the R2 objects a static page reads in the browser
 * (lib/object-gate.mjs) -- is answered here, before the Next server loads, so it costs about
 * a millisecond of the Free plan's 10 ms rather than a Next request's 60-600 ms. Everything
 * else goes to OpenNext unchanged, except the static pages (scripts/static-pages.mjs): they run
 * the Worker first so a client navigation's RSC request gets the prerendered payload rather than
 * the HTML (lib/static-pages.mjs); their HTML is read from the assets by its file name.
 */
// @ts-expect-error: written by `opennextjs-cloudflare build`, resolved by wrangler.
import openNext from "./.open-next/worker.js";
// @ts-expect-error: written by scripts/static-pages.mjs after the build.
import STATIC_PAGES from "./.open-next/static-pages.json";
import { OBJECTS_PATH, serveObject, tokenVerifier } from "./lib/object-gate.mjs";
import { RSC_VARY, rscAsset } from "./lib/static-pages.mjs";

// The Durable Object classes OpenNext's entry exports (none is bound today; kept so one can be).
// @ts-expect-error: as above.
export * from "./.open-next/worker.js";

let verify;

const worker = {
  fetch(request, env, ctx) {
    const { pathname } = new URL(request.url);
    if (Object.hasOwn(STATIC_PAGES, pathname)) return serveStatic(request, env.ASSETS, pathname, STATIC_PAGES[pathname]);
    if (pathname === OBJECTS_PATH) {
      verify ??= tokenVerifier(env.NEXT_PUBLIC_SUPABASE_URL, env.NEXT_PUBLIC_SUPABASE_ANON_KEY);
      return serveObject(request, env.MARKET_DATA, verify);
    }
    return openNext.fetch(request, env, ctx);
  },
};

async function serveStatic(request, assets, page, headers) {
  const target = rscAsset(page, request.headers.get("rsc"), request.headers.get("next-router-segment-prefetch"));
  // A Request built over the original keeps its method and conditional headers (If-None-Match).
  const asset = (path) => assets.fetch(new Request(new URL(path, request.url), request));
  if (!target) return asset(`${page}.html`);
  const file = target.asset ? await asset(target.asset) : null;
  if (!file?.ok) return new Response(null, { status: 404, headers: { vary: RSC_VARY } });
  return new Response(file.body, {
    headers: {
      "content-type": "text/x-component",
      "cache-control": file.headers.get("cache-control") ?? "public, max-age=0, must-revalidate",
      vary: RSC_VARY,
      ...headers,
      // As Next marks a prerendered segment (OpenNext's cache interceptor does the same).
      ...(target.segment ? { "x-nextjs-prerender": "1", "x-nextjs-postponed": "2" } : {}),
    },
  });
}

export default worker;
