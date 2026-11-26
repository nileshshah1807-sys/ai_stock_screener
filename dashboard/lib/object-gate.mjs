/**
 * `/api/objects?market=NSE&name=fpi-flows`: one R2 object a static page reads in the
 * browser, passed through unparsed to a viewer with access. Served by worker.ts
 * before the Next server loads (a request costs ~1 ms of CPU, not Next's 60-600 ms);
 * app/api/objects/route.ts answers the same way under `next dev`.
 *
 * Only the objects named here, and only display evidence with no rating: the
 * objects bypass row-level security, so the token (a Bearer header, verified
 * against the project's signing key) is the gate. A token with no plan claim is
 * refused rather than looked up in the allowlist: the shell refreshes it first.
 */

import { createClient } from "@supabase/supabase-js";

import { shellAccess } from "./shell-access.mjs";

export const OBJECTS_PATH = "/api/objects";

/**
 * A token's claims, verified locally against the project's ES256 key (getClaims, as the
 * proxy does) or null. One client per instance, so auth-js keeps the key between requests.
 */
export function tokenVerifier(url, anonKey) {
  const { auth } = createClient(url, anonKey, {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
  });
  return async (token) => {
    const { data, error } = await auth.getClaims(token);
    return error ? null : (data?.claims ?? null);
  };
}

const OBJECTS = {
  "fii-dii-flows": (market) => `live/${market}/fii-dii-flows.json`,
  "fpi-flows": (market) => `live/${market}/fpi-flows.json`,
  // Today's five-minute line of each headline index (workers/live_quotes.py publish_intraday).
  intraday: (market) => `live/${market}/intraday.json`,
  "sector-directory": (market) => `sectors/${market}/directory.json`,
};
const MARKETS = new Set(["NSE", "US"]);

/** The R2 key for a named object, or null for anything not on the list. */
export function objectKey(market, name) {
  if (!MARKETS.has(market) || !Object.hasOwn(OBJECTS, name ?? "")) return null;
  return OBJECTS[name](market);
}

function refuse(status, error) {
  return new Response(JSON.stringify({ error }), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

/**
 * @param {Request} request
 * @param {{ get(key: string): Promise<{ body: ReadableStream } | null> } | undefined} bucket the MARKET_DATA binding
 * @param {(token: string) => Promise<Record<string, unknown> | null>} verify the token's claims, or null when it does not verify
 */
export async function serveObject(request, bucket, verify) {
  const params = new URL(request.url).searchParams;
  const key = objectKey(params.get("market"), params.get("name"));
  if (!key) return refuse(400, "bad request");
  const token = /^Bearer (\S+)$/.exec(request.headers.get("authorization") ?? "")?.[1];
  const claims = token ? await verify(token).catch(() => null) : null;
  if (shellAccess(claims, "/").kind !== "viewer") return refuse(401, "unauthorized");
  if (!bucket) return refuse(503, "no bucket");
  const object = await bucket.get(key);
  if (!object) return refuse(404, "not published");
  // private: per viewer; the objects are rewritten at most every few minutes.
  return new Response(object.body, {
    headers: { "content-type": "application/json", "cache-control": "private, max-age=60" },
  });
}
