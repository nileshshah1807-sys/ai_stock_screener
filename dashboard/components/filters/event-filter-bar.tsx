"use client";

import { useMemo, useOptimistic, useState, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Loader2, Plus, SlidersHorizontal, X } from "lucide-react";

import { FilterMultiSelect, type FilterOption } from "@/components/filters/filter-multi-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  MAX_RULES,
  GROWTH_METRICS,
  RULE_METRICS,
  RULE_OPERATORS,
  SIZE_UNITS,
  eventFilterEntries,
  eventFilterParams,
  isDefaultView,
  parseEventFilters,
  ruleLabel,
  withLists,
  type EventFilters,
  type FilterRule,
} from "@/lib/event-filters.mjs";
import type { MarketCode } from "@/lib/markets";

/** A filter of the page's own, shown at the right of the bar. */
export type EventFilterFacet = { param: string; label: string; options: FilterOption[] };

type Draft = { metric: string; op: string; value: string };

const SELECT_CLASS =
  "h-8 min-w-0 rounded-md border border-input bg-card px-3 text-sm shadow-xs outline-none hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

/**
 * The rules popover: each row is a figure, a comparison and a value, and all
 * rows must hold. Edited as a draft and applied together, so half a rule --
 * a figure chosen, no value typed yet -- never reaches the URL.
 */
function RuleBuilder({
  market,
  rules,
  metrics,
  onApply,
  disabled,
  title,
}: {
  market: MarketCode;
  metrics: Array<{ value: string; label: string; size?: boolean }>;
  rules: FilterRule[];
  onApply: (rules: FilterRule[]) => void;
  disabled: boolean;
  title?: string;
}) {
  const [open, setOpen] = useState(false);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const unit = SIZE_UNITS[market];

  const edit = (index: number, change: Partial<Draft>) =>
    setDrafts((current) => current.map((draft, at) => (at === index ? { ...draft, ...change } : draft)));

  const apply = () => {
    onApply(
      drafts
        .filter((draft) => draft.value.trim() !== "" && Number.isFinite(Number(draft.value)))
        .map((draft) => ({ metric: draft.metric, op: draft.op, value: Number(draft.value) })),
    );
    setOpen(false);
  };

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        // Each opening starts from what is applied, not from an abandoned draft.
        if (next) setDrafts(rules.map((rule) => ({ ...rule, value: String(rule.value) })));
        setOpen(next);
      }}
    >
      <PopoverTrigger
        disabled={disabled}
        render={
          <Button
            variant="outline"
            title={title ?? (rules.map((rule) => ruleLabel(rule, market)).join(" · ") || undefined)}
            aria-label={rules.length ? `Filters, ${rules.length} active` : "Filters"}
            className="gap-1.5"
          />
        }
      >
        <SlidersHorizontal className="size-3.5" aria-hidden />
        Filters
        {rules.length ? (
          <span className="tabular rounded-full bg-primary px-1.5 text-[10px] font-semibold leading-4 text-primary-foreground">
            {rules.length}
          </span>
        ) : null}
      </PopoverTrigger>

      <PopoverContent align="start" className="w-[min(32rem,calc(100vw-2rem))] gap-3">
        <form
          className="contents"
          onSubmit={(event) => {
            event.preventDefault();
            apply();
          }}
        >
          {drafts.length ? (
            <ul className="space-y-2">
              {drafts.map((draft, index) => {
                const chosen = metrics.find((item) => item.value === draft.metric);
                const sized = chosen?.size;
                const percent = Boolean(chosen && "growth" in chosen);
                return (
                  <li key={index} className="flex items-center gap-1.5">
                    <select
                      value={draft.metric}
                      onChange={(event) => edit(index, { metric: event.target.value })}
                      aria-label="Figure"
                      className={`${SELECT_CLASS} flex-1`}
                    >
                      {metrics.map((item) => (
                        <option key={item.value} value={item.value}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                    <select
                      value={draft.op}
                      onChange={(event) => edit(index, { op: event.target.value })}
                      aria-label="Comparison"
                      className={SELECT_CLASS}
                    >
                      {RULE_OPERATORS.map((item) => (
                        <option key={item.value} value={item.value}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                    <Input
                      type="number"
                      step="any"
                      inputMode="decimal"
                      value={draft.value}
                      onChange={(event) => edit(index, { value: event.target.value })}
                      placeholder="Value"
                      aria-label={sized ? `Value in ${unit.symbol} ${unit.suffix}` : percent ? "Value in percent" : "Value"}
                      className="tabular h-8 w-24"
                    />
                    <span className="w-9 shrink-0 text-xs text-muted-foreground">
                      {sized ? `${unit.symbol} ${unit.suffix}` : percent ? "%" : ""}
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Remove this filter"
                      onClick={() => setDrafts((current) => current.filter((_, at) => at !== index))}
                    >
                      <X className="size-3.5" aria-hidden />
                    </Button>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="px-1 text-xs text-muted-foreground">
              No filters. Companies of every size are shown.
            </p>
          )}

          <div className="flex items-center justify-between gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={drafts.length >= MAX_RULES}
              onClick={() =>
                setDrafts((current) => [...current, { metric: metrics[0].value, op: "gte", value: "" }])
              }
            >
              <Plus className="size-3.5" aria-hidden />
              Add filter
            </Button>
            <Button type="submit" size="sm">
              Apply
            </Button>
          </div>
          <p className="px-1 text-[11px] leading-snug text-muted-foreground">
            Figures are from the latest screener run. A company the run does not hold, or one with
            the figure unreported, passes no filter.
            {metrics.some((item) => "growth" in item)
              ? " Growth is the card's own, on the basis it opens on; a loss, or a quarter the company did not file, has no growth rate and passes no growth filter."
              : ""}
          </p>
        </form>
      </PopoverContent>
    </Popover>
  );
}

/**
 * The filter bar above a feed of company events: rules on a company's
 * figures, its industry, the viewer's watchlists, and whatever facets the
 * page adds of its own.
 *
 * Every choice is written to the URL and the server renders the feed from it,
 * so a filtered view survives a reload and can be shared. The bar shows a
 * choice the moment it is made and the feed follows when the server answers.
 */
export function EventFilterBar({
  market,
  filters,
  defaultScope,
  industries,
  watchlists,
  facets = [],
  factsAvailable = true,
  growth = false,
}: {
  market: MarketCode;
  /** The filters the server rendered with. */
  filters: EventFilters;
  /** What the page shows when the URL names no scope. */
  defaultScope: "all" | "watchlists";
  industries: FilterOption[];
  watchlists: FilterOption[];
  facets?: EventFilterFacet[];
  /** False when the run could not be read, so rules and industries cannot apply. */
  factsAvailable?: boolean;
  /** Offer rules on the growth of a result (Results only). */
  growth?: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [pending, startTransition] = useTransition();
  const [shown, setShown] = useOptimistic(filters);

  const context = useMemo(
    () => ({ market, listIds: watchlists.map((item) => item.value), defaultScope, facets, growth }),
    [market, watchlists, defaultScope, facets, growth],
  );

  const apply = (next: EventFilters) => {
    // Params that are not filters -- a page's search text -- ride along.
    const params = new URLSearchParams(searchParams.toString());
    for (const key of eventFilterParams(context)) params.delete(key);
    for (const [key, value] of eventFilterEntries(next, context)) params.append(key, value);
    const text = params.toString();
    startTransition(() => {
      setShown(next);
      router.push(text ? `${pathname}?${text}` : pathname, { scroll: false });
    });
  };

  const unavailable = factsAvailable
    ? undefined
    : "The latest run could not be read, so there is nothing to filter by.";

  return (
    <div className="flex flex-wrap items-center gap-2">
      <RuleBuilder
        market={market}
        metrics={growth ? [...RULE_METRICS, ...GROWTH_METRICS] : RULE_METRICS}
        rules={shown.rules}
        onApply={(rules) => apply({ ...shown, rules })}
        disabled={!factsAvailable}
        title={unavailable}
      />
      <FilterMultiSelect
        label="Industry"
        options={industries}
        selected={shown.industries}
        onChange={(next) => apply({ ...shown, industries: next })}
        searchable
        disabled={!factsAvailable}
        title={unavailable}
      />
      <FilterMultiSelect
        label="Watchlist"
        options={watchlists}
        selected={shown.lists}
        onChange={(next) => apply(withLists(shown, next, market))}
        searchable={watchlists.length > 8}
        emptyText="No watchlists yet."
      />

      {pending ? (
        <Loader2 className="size-3.5 animate-spin text-muted-foreground" aria-label="Updating" />
      ) : null}
      {isDefaultView(shown, context) ? null : (
        <Button variant="ghost" className="gap-1" onClick={() => apply(parseEventFilters({}, context))}>
          <X className="size-3.5" aria-hidden />
          Reset
        </Button>
      )}

      {facets.length ? (
        <div className="flex flex-wrap items-center gap-2 sm:ml-auto">
          {facets.map((facet) => (
            <FilterMultiSelect
              key={facet.param}
              label={facet.label}
              options={facet.options}
              selected={shown.facets[facet.param] ?? []}
              onChange={(next) =>
                apply({ ...shown, facets: { ...shown.facets, [facet.param]: next } })
              }
              align="end"
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
