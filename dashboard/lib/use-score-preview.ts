"use client";

import { useDeferredValue, useEffect, useMemo, useState } from "react";

import { outlookSince } from "@/lib/concalls.mjs";
import { RUN_COLUMNS, topByMix } from "@/lib/custom-score.mjs";
import { lazyClient } from "@/lib/supabase/lazy-client";

type Row = Record<string, unknown>;
type Run = { rows: Row[]; outlooks: Map<string, number> };

const PAGE = 1000;
// One read per market and run per page view: the run does not change under an open builder.
// Rows and calls are kept apart, so turning the call measure on reads the calls alone.
const cache = new Map<string, Promise<unknown>>();

function once<T>(key: string, read: () => Promise<T>): Promise<T> {
  let value = cache.get(key) as Promise<T> | undefined;
  if (!value) {
    value = read();
    value.catch(() => cache.delete(key)); // a failed read is tried again next open
    cache.set(key, value);
  }
  return value;
}

async function readAll(read: (from: number, to: number) => PromiseLike<{ data: unknown; error: { message: string } | null }>) {
  const rows: Row[] = [];
  for (let from = 0; ; from += PAGE) {
    const { data, error } = await read(from, from + PAGE - 1);
    if (error) throw new Error(error.message);
    const page = (data ?? []) as Row[];
    rows.push(...page);
    if (page.length < PAGE) return rows;
  }
}

/**
 * The run as lib/queries.ts readRunScores reads it, but from the browser
 * straight to Supabase as the viewer (RLS, the *_visible view), so the live
 * preview costs the Worker nothing. Call outlooks are D1's alone, so they come
 * from `/api/live?kind=calls`, one shared read per market and day.
 * shortcut: the run still reads Supabase even when TABLE_BACKEND moves
 * screener_snapshot to D1; move it to /api/live when that lands (docs/d1_migration_plan.md).
 */
async function readRun(market: string, runDate: string, withCalls: boolean): Promise<Run> {
  const client = await lazyClient();
  const [rows, calls] = await Promise.all([
    once(`rows:${market}:${runDate}`, () =>
      readAll((from, to) =>
        client
          .from("screener_snapshot_visible")
          .select([...RUN_COLUMNS, "company"].join(","))
          .eq("market", market)
          .eq("run_date", runDate)
          .is("unrated_reason", null)
          .order("symbol", { ascending: true })
          .range(from, to),
      ),
    ),
    withCalls
      ? once(`calls:${market}:${runDate}`, async () => {
          const query = new URLSearchParams({ kind: "calls", market, since: outlookSince(runDate) });
          const response = await fetch(`/api/live?${query}`);
          if (!response.ok) throw new Error(`call outlooks: ${response.status}`);
          const { data } = (await response.json()) as { data: Record<string, number> };
          return new Map(Object.entries(data));
        })
      : Promise.resolve(new Map<string, number>()),
  ]);
  return { rows, outlooks: calls };
}

export type PreviewRow = { symbol: string; company: string | null; score: number };
export type Preview = { state: "loading" | "ready" | "failed"; top: PreviewRow[] };

/** The first `size` stocks by the viewer's draft mix, worked out in the browser while `open`. */
export function useScorePreview(
  open: boolean,
  market: string,
  runDate: string | null,
  weights: Record<string, number>,
  size = 5,
): Preview {
  const withCalls = (weights.c ?? 0) > 0;
  const [run, setRun] = useState<{ key: string; value: Run | null; failed: boolean } | null>(null);
  const key = `${market}:${runDate}:${withCalls}`;

  useEffect(() => {
    if (!open || !runDate) return;
    let live = true;
    readRun(market, runDate, withCalls).then(
      (value) => live && setRun({ key, value, failed: false }),
      () => live && setRun({ key, value: null, failed: true }),
    );
    return () => {
      live = false;
    };
  }, [open, market, runDate, withCalls, key]);

  // Dragging stays smooth: the ranking follows the slider a frame behind, never blocks it.
  const deferred = useDeferredValue(weights);
  const ready = run?.key === key ? run.value : null;
  const top = useMemo(() => (ready ? topByMix(ready.rows, deferred, ready.outlooks, size) : []), [ready, deferred, size]);

  if (run?.key === key && run.failed) return { state: "failed", top: [] };
  return { state: ready ? "ready" : "loading", top };
}
