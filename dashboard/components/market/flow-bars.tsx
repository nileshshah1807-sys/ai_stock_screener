"use client";

import { useState } from "react";

import { FLOW_INK, FLOW_LABEL, flowFormat, type FlowCategory, type FlowSession } from "@/components/market/flow-format";
import { formatDate } from "@/lib/format";
import type { Market } from "@/lib/markets";
import { cn } from "@/lib/utils";

const CATEGORIES: FlowCategory[] = ["FII", "DII"];

/** The fewest slots the chart divides into, so a short history keeps thin bars. */
const MIN_SLOTS = 20;

const W = 600;
const H = 120;

/**
 * Paired daily bars of FII and DII net buying. The session under the pointer
 * (or chosen with the arrow keys) is outlined and written out below the
 * chart -- net, bought and sold for each -- so no figure hides in a tooltip.
 * With nothing chosen the readout shows the latest session.
 */
export function FlowBars({ market, sessions }: { market: Market; sessions: FlowSession[] }) {
  const [active, setActive] = useState<number | null>(null);
  const { money, signed, tone } = flowFormat(market);

  const slots = Math.max(sessions.length, MIN_SLOTS);
  const slot = W / slots;
  const left = W - sessions.length * slot;
  const peak = Math.max(1, ...sessions.flatMap((entry) => CATEGORIES.map((key) => Math.abs(entry[key]?.net ?? 0))));
  const y = (value: number) => H / 2 - (value / peak) * (H / 2 - 2);

  const shown = sessions[active ?? sessions.length - 1];
  const pick = (index: number) => setActive(Math.max(0, Math.min(sessions.length - 1, index)));

  const onPointer = (event: React.PointerEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - box.left) / box.width) * W;
    setActive(x < left ? null : Math.min(sessions.length - 1, Math.floor((x - left) / slot)));
  };

  const onKey = (event: React.KeyboardEvent<SVGSVGElement>) => {
    const at = active ?? sessions.length - 1;
    const moves: Record<string, number> = { ArrowLeft: at - 1, ArrowRight: at + 1, Home: 0, End: sessions.length - 1 };
    if (event.key in moves) {
      event.preventDefault();
      pick(moves[event.key]);
    }
  };

  return (
    <figure className="min-w-0">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="block h-28 w-full cursor-crosshair touch-pan-y rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        role="img"
        tabIndex={0}
        aria-label={`Daily net buying by FIIs and DIIs, ${sessions.length} sessions from ${formatDate(sessions[0].session)}. Arrow keys step through the sessions.`}
        onPointerMove={onPointer}
        onPointerDown={onPointer}
        onPointerLeave={() => setActive(null)}
        onKeyDown={onKey}
        onBlur={() => setActive(null)}
      >
        {active !== null ? (
          <rect x={left + active * slot} y={0} width={slot} height={H} fill="var(--control-hover)" />
        ) : null}
        <line x1={0} x2={W} y1={H / 2} y2={H / 2} stroke="var(--border)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
        {sessions.map((entry, index) =>
          CATEGORIES.map((key, k) => {
            const net = entry[key]?.net;
            if (net === null || net === undefined) return null;
            return (
              <rect
                key={`${entry.session}-${key}`}
                x={left + index * slot + slot * (0.12 + k * 0.4)}
                width={slot * 0.36}
                y={Math.min(y(net), H / 2)}
                height={Math.max(Math.abs(y(net) - H / 2), 1)}
                fill={FLOW_INK[key]}
                opacity={active === null || active === index ? 1 : 0.45}
                rx={1}
              />
            );
          }),
        )}
      </svg>

      <figcaption className="mt-2 space-y-1.5 text-xs text-muted-foreground">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <span className="tabular">{formatDate(sessions[0].session)}</span>
          <span className="tabular">{formatDate(sessions.at(-1)!.session)}</span>
        </div>
        <p aria-live="polite" className="tabular flex min-h-5 flex-wrap items-baseline gap-x-4 gap-y-1 border-t border-border/60 pt-1.5">
          <span className="font-medium text-foreground">{formatDate(shown.session)}</span>
          {CATEGORIES.map((key) => {
            const flow = shown[key];
            return (
              <span key={key} className="inline-flex flex-wrap items-baseline gap-x-1.5">
                <span className="size-2 self-center rounded-[2px]" style={{ background: FLOW_INK[key] }} aria-hidden />
                {FLOW_LABEL[key]}
                <span className={cn("font-mono font-semibold", tone(flow?.net))}>{signed(flow?.net)}</span>
                <span className="font-mono">
                  bought {money(flow?.buy)}, sold {money(flow?.sell)}
                </span>
              </span>
            );
          })}
        </p>
      </figcaption>
    </figure>
  );
}
