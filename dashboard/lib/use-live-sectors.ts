"use client";

import { useEffect, useState } from "react";

import { nextPollDelay } from "@/lib/live-quotes.mjs";
import type { MarketCode } from "@/lib/markets";
import { liveApi } from "@/lib/supabase/lazy-client";

/** One sector's change in the live session (workers/sectors.live_sector_changes). */
export type LiveSector = {
  slug: string;
  session: string;
  d1: number | null;
  advancing: number;
  declining: number;
  traded: number;
  /** When the worker wrote the object: the reading's time and freshness. */
  written_at: string | null;
};

type Answer = { rows: Omit<LiveSector, "written_at">[]; written_at: string | null };

/**
 * Each sector's live change by slug, from `live/{MARKET}/sectors.json`
 * through /api/live: read after render, again after each live-quotes run
 * while the tab is visible, and once on return to it. Empty until it arrives.
 */
export function useLiveSectors(market: MarketCode | null): Map<string, LiveSector> {
  const [live, setLive] = useState(() => new Map<string, LiveSector>());

  useEffect(() => {
    if (!market) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    const tick = async () => {
      clearTimeout(timer);
      if (document.visibilityState !== "visible") return;
      const { data, error } = await liveApi({ market, kind: "sectors" });
      if (stopped) return;
      const answer = error ? null : (data as Answer | null);
      if (answer) setLive(new Map(answer.rows.map((row) => [row.slug, { ...row, written_at: answer.written_at }])));
      clearTimeout(timer);
      timer = setTimeout(tick, nextPollDelay(answer?.written_at ?? null, Date.now()));
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") void tick();
    };

    void tick();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [market]);

  return live;
}
