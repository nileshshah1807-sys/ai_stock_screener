import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    /*
     * Client Router Cache retention.
     *
     * `dynamic` has defaulted to 0 since Next 15, meaning a segment is dropped
     * the instant you navigate away from it: going Screener -> Movers ->
     * Screener re-runs the whole query chain, and every one of those round
     * trips costs ~250ms against this Supabase origin. That is the single
     * biggest contributor to navigation feeling slow.
     *
     * 60s is safe here specifically because the underlying data is a daily
     * batch published once at 16:30 IST -- it is not a live feed, so a minute
     * of staleness cannot show a stale price that a fresh read would not also
     * show. Back/forward and repeat navigation inside that window are served
     * from memory and are effectively instant.
     *
     * This does not weaken authorization: the Client Router Cache is per-tab
     * in-memory only, and requireAccess() still runs on the server for any
     * request that actually reaches it.
     */
    staleTimes: {
      dynamic: 60,
      static: 300,
    },
  },
};

export default nextConfig;
