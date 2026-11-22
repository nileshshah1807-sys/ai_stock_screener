import { SAMPLE_CALLS, toneName } from "@/lib/landing.mjs";

/**
 * The Concalls page as two miniatures, one call per market, read two different
 * ways. Neutral ink throughout: a stance is a reading of the call, not a verdict.
 * Invented companies; the caller captions it.
 */
export function Calls() {
  return (
    <ul data-reveal className="grid gap-3 md:grid-cols-2">
      {SAMPLE_CALLS.map((call) => (
        <li key={call.market} className="panel p-5">
          <p className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
            <span className="rounded bg-(--control) px-1.5 py-0.5 font-medium">{call.where}</span>
            {call.quarter}
          </p>
          <h3 className="mt-3 text-lead font-semibold">{call.name}</h3>
          <ul className="mt-3 space-y-1.5 text-sm">
            {call.signals.map((s) => (
              <li key={s} className="flex items-center gap-2.5">
                <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-muted-foreground" />
                {s}
              </li>
            ))}
          </ul>
          <p className="mt-5 flex items-baseline justify-between gap-3 border-t pt-4">
            <span className="text-xs text-muted-foreground">Management stance</span>
            <span className="font-semibold">
              {toneName(call.score)} <span className="tabular-nums text-muted-foreground">· {call.score}</span>
            </span>
          </p>
        </li>
      ))}
  </ul>
  );
}
