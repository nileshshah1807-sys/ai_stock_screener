import { defineCloudflareConfig } from "@opennextjs/cloudflare";
import r2IncrementalCache from "@opennextjs/cloudflare/overrides/incremental-cache/r2-incremental-cache";
import { withRegionalCache } from "@opennextjs/cloudflare/overrides/incremental-cache/regional-cache";
import memoryQueue from "@opennextjs/cloudflare/overrides/queue/memory-queue";

/*
 * `unstable_cache` (lib/home-cache.ts, lib/results.ts, lib/queries.ts) needs an
 * incremental cache on Workers or nothing is kept between requests. R2, not KV:
 * the free KV plan allows 1,000 writes a day and these entries are rewritten
 * every few minutes; R2's free plan allows a million writes a month. The
 * regional cache keeps hot entries in front of it.
 *
 * The queue refreshes a page built with `revalidate` (the landing page, Refunds) once it is stale,
 * through the WORKER_SELF_REFERENCE binding in wrangler.jsonc; without one such a page would keep
 * its build-time copy until the next deploy.
 */
export default defineCloudflareConfig({
  incrementalCache: withRegionalCache(r2IncrementalCache, { mode: "long-lived", shouldLazilyUpdateOnCacheHit: true }),
  queue: memoryQueue,
  // A static or ISR page (/, /login, /refunds) is served from the cache before the Next server
  // loads: most of a request's CPU is Next itself, and the Free plan allows 10 ms.
  enableCacheInterception: true,
});
