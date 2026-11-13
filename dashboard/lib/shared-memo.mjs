/**
 * A per-server-instance memo for reads that are the same for every viewer who
 * has access and change on a known beat (a quote run, the evening run). The
 * first request after the window pays the read, the rest are served from
 * memory, so Home's cards no longer hit the database cold per request.
 *
 * Only for data that carries no per-viewer field (no rating): the loader runs
 * under whichever viewer asked first. A result `keep` rejects (a failed or
 * empty read) is returned but not remembered, so it is retried.
 *
 * @template T
 * @param {number} ttlMs
 * @param {number} [max] entries before the memo is cleared
 */
export function sharedMemo(ttlMs, max = 50) {
  /** @type {Map<string, { at: number, value: T }>} */
  const kept = new Map();
  /**
   * @param {string} key
   * @param {() => Promise<T>} load
   * @param {(value: T) => boolean} [keep]
   * @param {number} [now] epoch ms
   */
  return async (key, load, keep = () => true, now = Date.now()) => {
    const hit = kept.get(key);
    if (hit && now - hit.at < ttlMs) return hit.value;
    const value = await load();
    if (keep(value)) {
      if (kept.size >= max) kept.clear();
      kept.set(key, { at: now, value });
    }
    return value;
  };
}

/**
 * The window a shared-cache entry belongs to, for its key: one per
 * `revalidate` seconds.
 *
 * `unstable_cache` hands back a stale entry and refreshes it behind the
 * request, so a key few viewers read (a filter combination) showed what it
 * held hours ago. With the window in the key an entry is never read past its
 * window, and a new window is one ordinary miss: no extra read on any hit
 * (a stamp checked after the read cost a second one and put signed-in pages
 * over the Worker's limits, 13 Nov 2026). Each key's windows are offset by a
 * hash of the key, so a page's reads do not all miss in the same request.
 *
 * @param {number} revalidate seconds
 * @param {string} key the entry's other key parts, joined
 * @param {number} [now] epoch ms
 */
export function cacheWindow(revalidate, key, now = Date.now()) {
  const span = revalidate * 1000;
  let offset = 0;
  for (const char of key) offset = (offset * 31 + char.charCodeAt(0)) % span;
  return String(Math.floor((now + offset) / span));
}
