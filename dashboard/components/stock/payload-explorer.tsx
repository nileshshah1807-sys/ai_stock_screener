"use client";

import { useDeferredValue, useMemo, useState } from "react";
import { Search } from "lucide-react";

import { Input } from "@/components/ui/input";
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

function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return MISSING;
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  }
  return String(value);
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
        !renderValue(value).toLowerCase().includes(query)
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

      <div className="max-h-[32rem] space-y-4 overflow-y-auto pr-1">
        {groups.map(([group, rows]) => (
          <div key={group}>
            <h3 className="sticky top-0 bg-card py-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              {group}
            </h3>
            <dl className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
              {rows.map(([key, value]) => (
                <div
                  key={key}
                  className="flex items-baseline justify-between gap-3 border-b border-dashed py-1"
                >
                  <dt className="min-w-0 truncate font-mono text-[11px] text-muted-foreground">
                    {key}
                  </dt>
                  <dd className="tabular shrink-0 text-right font-mono text-[11px]">
                    {renderValue(value)}
                  </dd>
                </div>
              ))}
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
