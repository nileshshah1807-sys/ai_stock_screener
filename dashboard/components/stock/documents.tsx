"use client";

import { useState } from "react";
import { ExternalLink } from "lucide-react";

import { formatDate } from "@/lib/format";
import { groupDocuments } from "@/lib/documents.mjs";
import type { DocumentRow } from "@/lib/documents";
import { cn } from "@/lib/utils";

const SHOWN = 5;
const LINK =
  "inline-flex items-center gap-1 rounded font-medium hover:underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function Group({ id, label, items }: { id: string; label: string; items: ReturnType<typeof groupDocuments>[number]["items"] }) {
  const [all, setAll] = useState(false);
  const shown = all ? items : items.slice(0, SHOWN);
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
      {items.length > SHOWN ? (
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

/** The Documents tab: links by kind, newest first, with jump chips. See lib/documents.mjs. */
export function Documents({ rows, symbol }: { rows: DocumentRow[]; symbol: string }) {
  const groups = groupDocuments(rows);
  if (!groups.length) return <p className="text-sm text-muted-foreground">No documents yet.</p>;
  return (
    <div className="flex flex-col gap-5">
      <nav aria-label={`${symbol} document kinds`} className="flex flex-wrap gap-2">
        {groups.map((group) => (
          <a
            key={group.kind}
            href={`#doc-${group.kind}`}
            className="rounded-md px-3 py-1 text-[0.8125rem] font-medium text-muted-foreground ring-1 ring-inset ring-border hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {group.label} <span className="tabular">{group.items.length}</span>
          </a>
        ))}
      </nav>
      <div className="grid gap-x-8 gap-y-6 lg:grid-cols-2">
        {groups.map((group) => (
          <Group key={group.kind} id={`doc-${group.kind}`} label={group.label} items={group.items} />
        ))}
      </div>
    </div>
  );
}
