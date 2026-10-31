"use client";

import { useId, useState, type ReactNode } from "react";
import { Info } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * A page's title, with what used to be paragraphs of explanation behind the
 * same toggle the stock page's panels use (`PanelHeader`): one tap away, from
 * the keyboard too, and not on screen until asked for.
 */
export function PageTitle({ title, info }: { title: string; info?: ReactNode }) {
  const [open, setOpen] = useState(false);
  const infoId = useId();
  return (
    <div>
      <div className="flex items-center gap-1.5">
        <h1 className="text-title font-semibold">{title}</h1>
        {info ? (
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            aria-controls={infoId}
            aria-label={`About ${title}`}
            className={cn(
              "inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              open && "bg-muted text-foreground",
            )}
          >
            <Info className="size-4" aria-hidden />
          </button>
        ) : null}
      </div>
      {info ? (
        <div id={infoId} hidden={!open} className="mt-2 max-w-prose space-y-1.5 text-xs leading-relaxed text-muted-foreground">
          {info}
        </div>
      ) : null}
    </div>
  );
}
