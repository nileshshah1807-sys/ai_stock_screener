import { defineCloudflareConfig } from "@opennextjs/cloudflare";
import r2IncrementalCache from "@opennextjs/cloudflare/overrides/incremental-cache/r2-incremental-cache";
import { withRegionalCache } from "@opennextjs/cloudflare/overrides/incremental-cache/regional-cache";

/*
 * `unstable_cache` (lib/home-cache.ts, lib/results.ts, lib/queries.ts) needs an
 * incremental cache on Workers or nothing is kept between requests. R2, not KV:
 * the free KV plan allows 1,000 writes a day and these entries are rewritten
 * every few minutes; R2's free plan allows a million writes a month. The
 * regional cache keeps hot entries in front of it.
 */
export default defineCloudflareConfig({
  incrementalCache: withRegionalCache(r2IncrementalCache, { mode: "long-lived", shouldLazilyUpdateOnCacheHit: true }),
});
