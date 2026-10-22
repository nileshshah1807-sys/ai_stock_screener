"use client";

import { useId, useState } from "react";
import { Info } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * A panel's title row, with its explanation behind a toggle.
 *
 * The stock page ran a paragraph under every heading -- methodology, caveats,
 * how the number was built -- and a reader scanning for figures had to read
 * past all of it on every visit. The explanation is still one tap away, opens
 * from the keyboard and is announced as a disclosure; it is just not on
 * screen until asked for. `tag` is for the one fact a reader must not miss,
 * such as "Not scored", and stays visible.
 */
export function PanelHeader({
  title,
  info,
  tag,
}: {
  title: string;
  info?: React.ReactNode;
  tag?: string;
}) {
  const [open, setOpen] = useState(false);
  const infoId = useId();

  return (
    <div className="mb-4">
      <div className="flex items-center gap-2">
        <h2 className="text-lead font-semibold tracking-[-0.011em]">{title}</h2>
        {tag ? (
          <span className="rounded-md bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
            {tag}
          </span>
        ) : null}
        {info ? (
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            aria-controls={infoId}
            aria-label={`About ${title}`}
            className={cn(
              "ml-auto inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              open && "bg-muted text-foreground",
            )}
          >
            <Info className="size-4" aria-hidden />
          </button>
        ) : null}
      </div>
      {info ? (
        <div
          id={infoId}
          hidden={!open}
          className="mt-2 max-w-prose space-y-1.5 text-xs leading-relaxed text-muted-foreground"
        >
          {info}
        </div>
      ) : null}
    </div>
  );
}
