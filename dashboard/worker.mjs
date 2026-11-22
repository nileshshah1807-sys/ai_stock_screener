/*
 * The Worker's entry (`main` in wrangler.jsonc and wrangler.preview.jsonc), around the one
 * OpenNext builds. `/api/objects` -- the R2 objects a static page reads in the browser
 * (lib/object-gate.mjs) -- is answered here, before the Next server loads, so it costs about
 * a millisecond of the Free plan's 10 ms rather than a Next request's 60-600 ms. Everything
 * else goes to OpenNext unchanged. Static pages themselves never reach this file: Cloudflare
 * serves them from the assets directory (scripts/static-pages.mjs).
 */
// @ts-expect-error: written by `opennextjs-cloudflare build`, resolved by wrangler.
import openNext from "./.open-next/worker.js";
import { OBJECTS_PATH, serveObject, tokenVerifier } from "./lib/object-gate.mjs";

// The Durable Object classes OpenNext's entry exports (none is bound today; kept so one can be).
// @ts-expect-error: as above.
export * from "./.open-next/worker.js";

let verify;

const worker = {
  fetch(request, env, ctx) {
    if (new URL(request.url).pathname === OBJECTS_PATH) {
      verify ??= tokenVerifier(env.NEXT_PUBLIC_SUPABASE_URL, env.NEXT_PUBLIC_SUPABASE_ANON_KEY);
      return serveObject(request, env.MARKET_DATA, verify);
    }
    return openNext.fetch(request, env, ctx);
  },
};

export default worker;
