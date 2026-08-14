import "server-only";

/**
 * Opt-in server timing, enabled with SCREENER_TRACE=1.
 *
 * Next's request log reports one total per request, which cannot answer the
 * question that matters here: on a sort or filter click, does the work come
 * from the grid query alone, or is a layout re-rendering and dragging its
 * run-scoped reads along with it? This labels each span so the log shows
 * exactly which functions ran for a given navigation.
 *
 * Off by default, so it costs nothing in normal development or production.
 */
const ENABLED = process.env.SCREENER_TRACE === "1";

export async function trace<T>(label: string, fn: () => Promise<T>): Promise<T> {
  if (!ENABLED) return fn();

  const started = performance.now();
  try {
    return await fn();
  } finally {
    const ms = performance.now() - started;
    console.log(`      [trace] ${label.padEnd(28)} ${ms.toFixed(0).padStart(6)} ms`);
  }
}

/** Marks a render that happened at all, for spans with no useful duration. */
export function mark(label: string): void {
  if (!ENABLED) return;
  console.log(`      [trace] ${label}`);
}
