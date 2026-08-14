"use client";

import { useDeferredValue, useMemo, useState } from "react";
import { Search } from "lucide-react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { MISSING } from "@/lib/format";

/**
 * Every field of the source row, searchable.
 *
 * The typed columns cover what the grid needs, but the screener exports ~370
 * fields and the long tail is exactly where an audit question gets answered.
 * Rather than curating a subset and losing the rest, the complete record is
 * browsable here, grouped by the export's own prefix convention.
 */
function groupOf(key: string): string {
  const match = key.match(
    /^(DCF|Transcript|Red_Flag|Shadow_Red_Flag|Fund_Component|Tech_Component|Fundamental|Technical|Liquidity|NSE|Buy|Strong_Buy|Core|Portfolio|Turnover|Price_Bar|Demand_Proxy|Run|Valuation|Sector|Median|Avg)/,
  );
  return match ? match[1].replace(/_/g, " ") : "General";
}

const INTEGER_FORMAT = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 0,
});

/**
 * Formats one source value for display.
 *
 * Numbers get real treatment rather than `String(value)`:
 *
 *   - integers carry thousands separators, so 32663 reads as 32,663 instead of
 *     forcing the reader to count digits
 *   - fractions are trimmed to four decimals *and* stripped of trailing zeros,
 *     because the exporter emits fixed-scale decimals and a column of
 *     "88.2500 / 0.2049 / 1.0000" is mostly noise
 *
 * The kind is returned alongside the text so the row can style a figure
 * differently from a string without re-sniffing the type.
 */
function renderValue(value: unknown): {
  text: string;
  kind: "missing" | "boolean" | "number" | "text";
} {
  if (value === null || value === undefined || value === "") {
    return { text: MISSING, kind: "missing" };
  }
  if (typeof value === "boolean") {
    return { text: value ? "true" : "false", kind: "boolean" };
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    if (Number.isInteger(value)) {
      return { text: INTEGER_FORMAT.format(value), kind: "number" };
    }
    // parseFloat drops trailing zeros that toFixed always pads on.
    return { text: String(parseFloat(value.toFixed(4))), kind: "number" };
  }
  return { text: String(value), kind: "text" };
}

export function PayloadExplorer({
  payload,
}: {
  payload: Record<string, unknown>;
}) {
  const [term, setTerm] = useState("");
  // Filtering ~370 rows on every keystroke is cheap but not free; deferring
  // keeps the input responsive while the list catches up.
  const deferred = useDeferredValue(term);

  const groups = useMemo(() => {
    const query = deferred.trim().toLowerCase();
    const buckets = new Map<string, Array<[string, unknown]>>();

    for (const [key, value] of Object.entries(payload)) {
      if (
        query &&
        !key.toLowerCase().includes(query) &&
        !renderValue(value).text.toLowerCase().includes(query)
      ) {
        continue;
      }
      const group = groupOf(key);
      if (!buckets.has(group)) buckets.set(group, []);
      buckets.get(group)!.push([key, value]);
    }

    return [...buckets.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [payload, deferred]);

  const matchCount = groups.reduce((sum, [, rows]) => sum + rows.length, 0);

  return (
    <div>
      <div className="relative mb-3">
        <Search
          className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          type="search"
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          placeholder={`Search ${Object.keys(payload).length} fields…`}
          aria-label="Search all source fields"
          className="h-9 pl-8"
        />
      </div>

      <p className="mb-3 text-xs text-muted-foreground" aria-live="polite">
        {matchCount} field{matchCount === 1 ? "" : "s"}
        {deferred.trim() ? ` matching “${deferred.trim()}”` : ""}
      </p>

      {/*
        `overflow-x-hidden` plus a shrinkable value cell is what removes the
        horizontal scrollbar this panel used to carry. The value was previously
        `shrink-0`, so a single long field -- an ISO timestamp, a gate reason --
        forced the whole 370-row list wider than the panel and put a scrollbar
        under every one of them.
      */}
      <div className="max-h-[32rem] space-y-5 overflow-y-auto overflow-x-hidden pr-1">
        {groups.map(([group, rows]) => (
          <div key={group}>
            <h3 className="sticky top-0 z-10 flex items-center gap-2 bg-card py-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              {group}
              <span className="h-px flex-1 bg-border" aria-hidden />
              <span className="tabular font-normal">{rows.length}</span>
            </h3>
            <dl className="grid grid-cols-1 gap-x-8 sm:grid-cols-2">
              {rows.map(([key, value]) => {
                const { text, kind } = renderValue(value);
                return (
                  <div
                    key={key}
                    className="flex items-baseline justify-between gap-4 border-b border-dashed py-1.5"
                  >
                    {/* The key is the label, so it yields space first: it
                        truncates while the value stays whole wherever it can. */}
                    <dt
                      className="min-w-0 shrink truncate text-[11px] text-muted-foreground"
                      title={key}
                    >
                      {key.replace(/_/g, " ")}
                    </dt>
                    <dd
                      className={cn(
                        "min-w-0 max-w-[60%] truncate text-right text-[11px]",
                        kind === "number" && "tabular font-medium",
                        kind === "missing" && "text-muted-foreground",
                        kind === "boolean" &&
                          (text === "true" ? "text-positive" : "text-muted-foreground"),
                      )}
                      title={text}
                    >
                      {text}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </div>
        ))}

        {!groups.length ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No field matches “{deferred}”.
          </p>
        ) : null}
      </div>
    </div>
  );
}
