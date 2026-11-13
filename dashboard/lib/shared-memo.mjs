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
 * A cached `{ at, value }` entry's value while it is at most `revalidate`
 * seconds old, else undefined (the caller reads live).
 *
 * `unstable_cache` hands back a stale entry and refreshes it behind the
 * request, so a key few viewers read (a filter combination) would show what it
 * held hours ago, missing the newest calls and results. An entry without a
 * stamp (written before this rule) is stale.
 *
 * @template T
 * @param {{ at: number, value: T } | undefined} entry
 * @param {number} revalidate seconds
 * @param {number} [now] epoch ms
 * @returns {T | undefined}
 */
export function freshValue(entry, revalidate, now = Date.now()) {
  return entry && now - entry.at <= revalidate * 1000 ? entry.value : undefined;
}
