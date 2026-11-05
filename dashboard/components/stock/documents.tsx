"use client";

import { useState } from "react";
import { ExternalLink } from "lucide-react";

import { SegmentedControl } from "@/components/segmented-control";
import { formatDate } from "@/lib/format";
import { groupDocuments } from "@/lib/documents.mjs";
import type { DocumentRow } from "@/lib/documents";
import { cn } from "@/lib/utils";

const SHOWN = 5;
const LINK =
  "inline-flex items-center gap-1 rounded font-medium hover:underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function Group({
  id,
  label,
  items,
  everything,
}: {
  id: string;
  label: string;
  items: ReturnType<typeof groupDocuments>[number]["items"];
  /** One kind on its own: every row, no "All N" cut. */
  everything: boolean;
}) {
  const [all, setAll] = useState(false);
  const shown = all || everything ? items : items.slice(0, SHOWN);
  return (
    <section id={id} aria-labelledby={`${id}-h`} className="min-w-0 scroll-mt-24">
      <h3 id={`${id}-h`} className="mb-1 text-sm font-semibold">
        {label} <span className="font-normal text-muted-foreground">{items.length}</span>
      </h3>
      <ul className="divide-y border-y">
        {shown.map((item) => (
          <li key={item.key} className="flex flex-col gap-0.5 py-2 text-sm sm:flex-row sm:items-baseline sm:gap-4">
            <time dateTime={item.date} className="tabular shrink-0 text-xs text-muted-foreground sm:w-24">
              {formatDate(item.date)}
            </time>
            {item.links.length === 1 ? (
              <a href={item.links[0].url} target="_blank" rel="noopener noreferrer" className={cn(LINK, "min-w-0")}>
                <span className="min-w-0">{item.title}</span>
                <ExternalLink className="size-3 shrink-0 text-muted-foreground" aria-hidden />
                <span className="sr-only">(opens in a new tab)</span>
              </a>
            ) : (
              <span className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-0.5">
                <span className="min-w-0">{item.title}</span>
                {item.links.map((link) => (
                  <a key={link.label} href={link.url} target="_blank" rel="noopener noreferrer" className={cn(LINK, "text-muted-foreground hover:text-foreground")}>
                    {link.label}
                    <ExternalLink className="size-3" aria-hidden />
                    <span className="sr-only">(opens in a new tab)</span>
                  </a>
                ))}
              </span>
            )}
          </li>
        ))}
      </ul>
      {items.length > SHOWN && !everything ? (
        <button
          type="button"
          onClick={() => setAll((value) => !value)}
          aria-expanded={all}
          className="mt-1 rounded text-xs font-medium text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {all ? "Show fewer" : `All ${items.length}`}
        </button>
      ) : null}
    </section>
  );
}

/** The Documents tab: links by kind, newest first; the control filters the grid to one kind. See lib/documents.mjs. */
export function Documents({ rows, symbol }: { rows: DocumentRow[]; symbol: string }) {
  const groups = groupDocuments(rows);
  const [kind, setKind] = useState("all");
  if (!groups.length) return <p className="text-sm text-muted-foreground">No documents yet.</p>;
  const only = groups.find((group) => group.kind === kind);
  const shown = only ? [only] : groups;
  return (
    <div className="flex flex-col gap-5">
      {/* Scrolls sideways rather than wrapping the track on a phone. */}
      <div className="-mx-1 overflow-x-auto overflow-y-hidden px-1 pb-1">
        <SegmentedControl
          label={`${symbol} document kinds`}
          value={only ? kind : "all"}
          onChange={setKind}
          options={[
            { value: "all", label: "All" },
            ...groups.map((group) => ({
              value: group.kind,
              label: (
                <>
                  {group.label} <span className="tabular ml-1 text-muted-foreground">{group.items.length}</span>
                </>
              ),
            })),
          ]}
        />
      </div>
      <div className={cn("grid gap-x-8 gap-y-6", !only && "lg:grid-cols-2")}>
        {shown.map((group) => (
          <Group key={group.kind} id={`doc-${group.kind}`} label={group.label} items={group.items} everything={!!only} />
        ))}
      </div>
    </div>
  );
}
