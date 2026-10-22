"use client";

import { useId, useState } from "react";
import { Info } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * One label/value pair, with its hint behind a toggle.
 *
 * A hint printed under every field made a ten-field panel read as forty lines.
 * Behind a button it costs nothing until asked for, and unlike a `title` it
 * opens on a tap and from the keyboard, and a screen reader is told it exists.
 * A hint that explains a warning is the exception: the caller passes
 * `hintOpen`, because a caution the reader has to go looking for is not one.
 */
export function FieldItem({
  label,
  value,
  hint,
  hintOpen = false,
  toneClass,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  hintOpen?: boolean;
  toneClass: string;
}) {
  const [open, setOpen] = useState(false);
  const hintId = useId();
  const shown = hintOpen || open;

  return (
    <div className="min-w-0">
      <dt className="flex items-center gap-1 text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
        {hint && !hintOpen ? (
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            aria-controls={hintId}
            aria-label={`About ${label}`}
            className={cn(
              // A 24px target around a 12px glyph; the negative margin keeps
              // the label's line height unchanged.
              "-my-1.5 inline-flex size-6 items-center justify-center rounded-md transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              open && "text-foreground",
            )}
          >
            <Info className="size-3" aria-hidden />
          </button>
        ) : null}
      </dt>
      <dd className={cn("tabular mt-0.5 break-words font-mono text-sm", toneClass)}>
        {value}
      </dd>
      {hint ? (
        <p
          id={hintId}
          hidden={!shown}
          className="mt-0.5 text-xs leading-snug text-muted-foreground"
        >
          {hint}
        </p>
      ) : null}
    </div>
  );
}
