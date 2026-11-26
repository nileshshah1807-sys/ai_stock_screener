"use client";

import { useEffect, useState } from "react";

import { readObject } from "@/lib/browser-objects";
import type { IntradayObject } from "@/lib/intraday.mjs";
import { nextPollDelay } from "@/lib/live-quotes.mjs";
import type { MarketCode } from "@/lib/markets";

/** Coming back to the tab reads again only past this; a quick tab flip asks for nothing. */
const REVISIT_MS = 60_000;

/**
 * Today's index lines (lib/intraday.mjs), read in the browser from R2 through
 * /api/objects, which the Worker answers before Next loads (about 1 ms of CPU).
 * Asked again when the worker's next run should have landed, as the live quotes
 * are, and not at all while the tab is hidden.
 */
export function useIntraday(market: MarketCode): IntradayObject | null {
  const [data, setData] = useState<IntradayObject | null>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    let writtenAt: string | null = null;
    let readAt = 0;

    const load = async () => {
      clearTimeout(timer);
      if (document.visibilityState !== "visible") return;
      readAt = Date.now();
      const next = await readObject<IntradayObject>(market, "intraday");
      if (stopped) return;
      if (next) {
        writtenAt = next.written_at ?? null;
        setData(next);
      }
      timer = setTimeout(load, nextPollDelay(writtenAt, Date.now()));
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible" && Date.now() - readAt > REVISIT_MS) void load();
    };

    void load();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [market]);

  return data;
}
