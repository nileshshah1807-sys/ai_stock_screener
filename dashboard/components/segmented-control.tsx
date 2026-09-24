"use client";

import { useRef } from "react";

import { GlassTrack } from "@/components/glass-track";
import { cn } from "@/lib/utils";

export type SegmentedOption<T extends string> = {
  value: T;
  /** A node, so a segment can swap a short label in on narrow screens. */
  label: React.ReactNode;
  title?: string;
};

/**
 * Pick one of a few options, on a glass track whose lens glides between them.
 *
 * The one place this control's behaviour lives: selection on pointer-down (the
 * lens starts moving the instant the finger lands, and GlassTrack retargets it
 * mid-flight if another segment is pressed), a roving tab stop, and arrow /
 * Home / End keys that move the selection and the focus together.
 *
 * `kind` sets the semantics, not the look:
 *
 * - `radio` -- a setting that changes what is already on screen (a range, a
 *   unit). Announced as a radio group.
 * - `tabs` -- switches between panels. Pass `idPrefix` and give each panel
 *   `id={`${idPrefix}-panel-${value}`}` and
 *   `aria-labelledby={`${idPrefix}-tab-${value}`}` so the pairing is announced.
 *
 * Navigation between URLs is not this component: those are links, and
 * NavLink / MarketSwitch put links on the same GlassTrack.
 */
export function SegmentedControl<T extends string>({
  label,
  value,
  onChange,
  options,
  kind = "radio",
  size = "sm",
  idPrefix,
  className,
}: {
  label: string;
  value: T;
  onChange: (value: T) => void;
  options: readonly SegmentedOption<T>[];
  kind?: "radio" | "tabs";
  size?: "sm" | "md";
  idPrefix?: string;
  className?: string;
}) {
  const buttons = useRef<Map<T, HTMLButtonElement>>(new Map());
  const itemRole = kind === "tabs" ? "tab" : "radio";

  const move = (next: T) => {
    onChange(next);
    buttons.current.get(next)?.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    const index = options.findIndex((option) => option.value === value);
    let target: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") target = index + 1;
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") target = index - 1;
    else if (event.key === "Home") target = 0;
    else if (event.key === "End") target = options.length - 1;
    if (target === null) return;
    event.preventDefault();
    move(options[(target + options.length) % options.length].value);
  };

  return (
    <GlassTrack
      label={label}
      role={kind === "tabs" ? "tablist" : "radiogroup"}
      className={cn("w-max gap-0.5 p-1", className)}
      onKeyDown={onKeyDown}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            ref={(node) => {
              if (node) buttons.current.set(option.value, node);
              else buttons.current.delete(option.value);
            }}
            type="button"
            role={itemRole}
            aria-checked={kind === "radio" ? active : undefined}
            aria-selected={kind === "tabs" ? active : undefined}
            id={idPrefix ? `${idPrefix}-tab-${option.value}` : undefined}
            aria-controls={kind === "tabs" && idPrefix ? `${idPrefix}-panel-${option.value}` : undefined}
            tabIndex={active ? 0 : -1}
            title={option.title}
            // Pointer-down, the moment the finger lands; click remains the
            // keyboard and assistive-technology path.
            onPointerDown={(event) => {
              if (event.button === 0) onChange(option.value);
            }}
            onClick={() => onChange(option.value)}
            className={cn(
              "relative inline-flex items-center justify-center whitespace-nowrap rounded-full",
              size === "md" ? "min-h-9 px-5 text-sm" : "min-h-8 min-w-10 px-3 text-[0.8125rem] sm:px-3.5",
              "transition-[color,transform] duration-(--duration-spring-bouncy) ease-(--ease-spring)",
              "active:scale-[0.95] active:duration-(--duration-press) active:ease-out",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
              active
                ? "font-semibold text-foreground"
                : "font-medium text-muted-foreground hover:text-foreground",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </GlassTrack>
  );
}
