"use client";

import { useCallback, useEffect, useMemo, useState, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ChevronDown, Search, SlidersHorizontal, X } from "lucide-react";

import { SearchInput } from "@/components/filters/live-search";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Sheet, SheetClose, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { ELIGIBILITY_CLASSES, RATINGS, STAGES } from "@/lib/types";
import { useShowRatings } from "@/components/market-provider";
import { PendingMarker } from "@/components/nav-pending";
import { RATING_FILTER_KEYS, publicText } from "@/lib/ratings.mjs";
import { RANGE_GROUPS, formatRange, readRanges, type RangeFilter } from "@/lib/screener-ranges.mjs";
import { useUrlDraft } from "@/lib/use-url-draft";
import { cn } from "@/lib/utils";

const TOGGLES = [
  {
    key: "actionable",
    label: "Executable only",
    hint: "Portfolio_Actionable: the target position can realistically be built at the configured participation rate.",
  },
  {
    key: "buyEligible",
    label: "Passes BUY gates",
    hint: "Coverage, trend, and data-quality gates all satisfied.",
  },
  {
    key: "excludeCapped",
    label: "Exclude capped",
    hint: "Hide rows whose rating is held below their score by a policy ceiling.",
  },
  {
    key: "transcript",
    label: "Scoring-eligible transcript",
    hint: "A current-cycle call that actually carries weight, not merely one on file.",
  },
  {
    key: "redFlags",
    label: "Has red flags",
    hint: "Shadow evidence only; never affects the live score or rating.",
  },
] as const;

/**
 * Model 5.0 only. Hidden entirely on a 4.x run, because these columns are null
 * there and PostgREST comparisons exclude nulls -- offering the control would
 * silently empty the grid rather than do nothing.
 */
const FACTOR_TOGGLES = [
  {
    key: "aboveMa200",
    label: "Above 200-day average",
    hint: "Price at or above its 200-day average.",
  },
] as const;

/** Which exchange a row trades on. Offered only on a run that carries BSE-only rows. */
export const LISTINGS = [
  {
    value: "nse",
    label: "Listed on NSE",
    hint: "Including companies also listed on BSE.",
  },
  {
    value: "bse",
    label: "Listed on BSE only",
    hint: "Mostly thinly traded. Scored from vendor data; exchange filings not connected yet.",
  },
] as const;

/** Pick-any choices on columns every viewer reads; the server matches any picked value. */
export const CHOICES = [
  {
    key: "board",
    label: "Board",
    options: [
      { value: "main", label: "Mainboard" },
      { value: "sme", label: "SME" },
    ],
  },
  {
    key: "liq",
    label: "Liquidity grade",
    options: [
      { value: "Group I - liquid", label: "Liquid" },
      { value: "Group II - less liquid", label: "Less liquid" },
      { value: "Group III - illiquid", label: "Illiquid" },
      { value: "Proxy only", label: "Not graded" },
    ],
  },
  {
    key: "dcf",
    label: "Reverse DCF",
    options: [
      { value: "Favorable", label: "Favourable" },
      { value: "Neutral", label: "Neutral" },
      { value: "Adverse", label: "Adverse" },
    ],
  },
  {
    key: "guide",
    label: "Concall guidance",
    options: [
      { value: "raised", label: "Raised" },
      { value: "maintained", label: "Maintained" },
      { value: "lowered", label: "Lowered" },
    ],
  },
] as const;

type Industries = { sector: string; industries: string[] }[];

const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** A pill that toggles one value. Same silhouette everywhere in the panel. */
function Pill({ active, onClick, children, small = false }: { active: boolean; onClick: () => void; children: React.ReactNode; small?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "tabular inline-flex items-center rounded-full font-medium",
        small ? "h-6 px-2 text-[11px]" : "h-8 px-3 text-xs",
        "transition-[background-color,color] duration-(--duration-fast) ease-(--ease-standard)",
        FOCUS,
        active
          ? "bg-primary text-primary-foreground"
          : "bg-(--control) text-muted-foreground hover:bg-(--control-hover) hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

/** A numeric bound that applies on Enter or when focus leaves; Escape restores it. */
function BoundInput({
  value,
  placeholder,
  label,
  onCommit,
}: {
  value: number | undefined;
  placeholder: string;
  label: string;
  onCommit: (value: number | undefined) => void;
}) {
  const commit = (text: string) => {
    const trimmed = text.trim();
    const next = trimmed === "" ? undefined : Number(trimmed);
    if (next !== undefined && !Number.isFinite(next)) return;
    if (next !== value) onCommit(next);
  };
  return (
    <Input
      // Keyed on the URL's value, so a preset or a chip removal shows here at once.
      key={String(value ?? "")}
      type="number"
      inputMode="decimal"
      step="any"
      defaultValue={value ?? ""}
      placeholder={placeholder}
      aria-label={label}
      className="tabular h-8 min-w-0 px-2.5 text-sm"
      onBlur={(event) => commit(event.target.value)}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit(event.currentTarget.value);
        if (event.key === "Escape") event.currentTarget.value = String(value ?? "");
      }}
    />
  );
}

function RangeRow({
  range,
  value,
  unit,
  onChange,
}: {
  range: RangeFilter;
  value: { min?: number; max?: number } | undefined;
  unit: string;
  onChange: (next: { min?: number; max?: number }) => void;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className={cn("text-sm", value ? "font-medium" : "text-foreground/85")}>{range.label}</span>
        {value ? (
          <button
            type="button"
            onClick={() => onChange({})}
            className={cn("rounded text-[11px] text-muted-foreground hover:text-foreground", FOCUS)}
            aria-label={`Reset ${range.label}`}
          >
            Reset
          </button>
        ) : null}
      </div>
      <div className="grid grid-cols-[1fr_auto_1fr_2.75rem] items-center gap-1.5">
        <BoundInput value={value?.min} placeholder="Min" label={`${range.label}, minimum`} onCommit={(min) => onChange({ ...value, min })} />
        <span className="text-xs text-muted-foreground" aria-hidden>
          to
        </span>
        <BoundInput value={value?.max} placeholder="Max" label={`${range.label}, maximum`} onCommit={(max) => onChange({ ...value, max })} />
        <span className="truncate text-xs text-muted-foreground">{unit}</span>
      </div>
      {range.presets?.length ? (
        <div className="flex flex-wrap gap-1">
          {range.presets.map((preset) => {
            const on = value?.min === preset.min && value?.max === preset.max;
            return (
              <Pill key={preset.label} small active={on} onClick={() => onChange(on ? {} : { min: preset.min, max: preset.max })}>
                {preset.label}
              </Pill>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

/** A collapsible group of filters, with how many of them are on. */
function Section({
  title,
  count,
  open,
  onToggle,
  children,
}: {
  title: string;
  count: number;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <section className="border-b border-border/70 last:border-b-0">
      <h3>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className={cn("flex w-full items-center gap-2 rounded py-3 text-left text-sm font-semibold", FOCUS)}
        >
          <span className="flex-1">{title}</span>
          {count ? (
            <span className="tabular rounded-full bg-primary/15 px-1.5 text-[11px] font-semibold text-primary">{count}</span>
          ) : null}
          <ChevronDown
            className={cn("size-4 text-muted-foreground transition-transform duration-(--duration-fast)", open && "rotate-180")}
            aria-hidden
          />
        </button>
      </h3>
      {open ? <div className="space-y-4 pb-4">{children}</div> : null}
    </section>
  );
}

function FlagRow({ id, label, hint, checked, onChange }: { id: string; label: string; hint: string; checked: boolean; onChange: () => void }) {
  return (
    <div className="flex items-start gap-2">
      <Checkbox id={id} checked={checked} onCheckedChange={onChange} className="mt-0.5" />
      <div className="min-w-0">
        <Label htmlFor={id} className="cursor-pointer text-sm font-normal">
          {label}
        </Label>
        <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">{hint}</p>
      </div>
    </div>
  );
}

const matches = (needle: string, ...haystack: string[]) =>
  !needle || haystack.some((text) => text.toLowerCase().includes(needle));

export function FilterBar({
  sectors,
  industries = [],
  factorModel = false,
  exchanges = false,
  sizeSuffix = "Cr",
}: {
  sectors: string[];
  /** Each sector's industries in this run. */
  industries?: Industries;
  factorModel?: boolean;
  /** Show the exchange choice: the run carries companies listed on BSE alone. */
  exchanges?: boolean;
  /** The market's size unit: "Cr" in India, "M" in the US. */
  sizeSuffix?: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [pending, startTransition] = useTransition();
  const showRatings = useShowRatings();
  // "Executable only" filters on portfolio_actionable, which tracks a BUY-grade rating.
  const toggles = TOGGLES.filter(
    (toggle) => showRatings || !(RATING_FILTER_KEYS.includes(toggle.key) || toggle.key === "actionable"),
  );

  // A saved view or a removed chip that changes `q` shows here, and the debounce
  // below does not write the old text back over it.
  const [query, setQuery] = useUrlDraft(searchParams.get("q") ?? "", (url) => url, (text) => text.trim());
  const [find, setFind] = useState("");
  const [industryFind, setIndustryFind] = useState("");
  const [opened, setOpened] = useState<Record<string, boolean>>({});

  const activeRatings = useMemo(() => searchParams.getAll("rating"), [searchParams]);
  const activeSectors = useMemo(() => searchParams.getAll("sector"), [searchParams]);
  const activeIndustries = useMemo(() => searchParams.getAll("industry"), [searchParams]);
  const ranges = useMemo(() => readRanges((key) => searchParams.get(key)), [searchParams]);

  const push = useCallback(
    (mutate: (params: URLSearchParams) => void) => {
      const params = new URLSearchParams(searchParams.toString());
      mutate(params);
      // Any filter change invalidates the current page offset; staying on
      // page 7 of a now-3-page result set would render an empty grid.
      params.delete("page");
      startTransition(() => {
        router.push(`${pathname}?${params.toString()}`, { scroll: false });
      });
    },
    [pathname, router, searchParams],
  );

  // Instant pass, every keystroke: hide the rows already on screen that do not
  // match, so typing answers on the next frame instead of after a server round
  // trip. It is the same case-insensitive substring test the server applies to
  // symbol and company, so the server's answer -- which also brings in matches
  // from other pages -- only ever adds rows; it never contradicts this one.
  // Re-run when the server's rows land, so a row that survives the re-render
  // is judged against the current text, not the text it was hidden under.
  useEffect(() => {
    const term = query.trim().toLowerCase();
    document
      .querySelectorAll<HTMLTableRowElement>("[data-screener-rows] > tr[data-match]")
      .forEach((row) => {
        row.hidden = Boolean(term) && !row.dataset.match!.includes(term);
      });
  }, [query, searchParams]);

  // Debounced server filter: one request per pause, not per keystroke. Short,
  // because the instant pass above already answered what is on screen.
  useEffect(() => {
    const current = searchParams.get("q") ?? "";
    if (query === current) return;

    const timer = setTimeout(() => {
      push((params) => {
        if (query.trim()) params.set("q", query.trim());
        else params.delete("q");
      });
    }, 150);

    return () => clearTimeout(timer);
  }, [query, push, searchParams]);

  const toggleValue = (key: string, value: string) => {
    push((params) => {
      const existing = params.getAll(key);
      params.delete(key);
      const next = existing.includes(value) ? existing.filter((item) => item !== value) : [...existing, value];
      next.forEach((item) => params.append(key, item));
    });
  };

  const toggleFlag = (key: string) => {
    push((params) => {
      if (params.get(key) === "1") params.delete(key);
      else params.set(key, "1");
    });
  };

  const setRange = (range: RangeFilter, next: { min?: number; max?: number }) => {
    push((params) => {
      // The old single-bound key gives way to the range key on any edit.
      if (range.legacyMin) params.delete(range.legacyMin);
      const text = formatRange(next);
      if (text) params.set(range.key, text);
      else params.delete(range.key);
    });
  };

  const on = (key: string) => searchParams.get(key) === "1";
  const choiceCount = CHOICES.reduce((sum, choice) => sum + searchParams.getAll(choice.key).length, 0);
  const stageCount = searchParams.getAll("stage").length + FACTOR_TOGGLES.filter((toggle) => on(toggle.key)).length;
  const evidenceCount =
    choiceCount +
    searchParams.getAll("listing").length +
    searchParams.getAll("eligibility").length +
    toggles.filter((toggle) => on(toggle.key)).length;
  // Counted whether or not this run offers the control, so a shared URL
  // carrying one still shows an accurate badge.
  const activeFilterCount =
    activeRatings.length +
    activeSectors.length +
    activeIndustries.length +
    Object.keys(ranges).length +
    stageCount +
    evidenceCount;

  const clearAll = () => {
    setQuery("");
    startTransition(() => router.push(pathname, { scroll: false }));
  };

  // While finding a filter every group with a match is open; otherwise a group
  // is open when the viewer opened it, or when it holds an active filter.
  const needle = find.trim().toLowerCase();
  const isOpen = (id: string, active: number, byDefault = false) =>
    needle ? true : (opened[id] ?? (active > 0 || byDefault));
  const flip = (id: string, current: boolean) => setOpened((state) => ({ ...state, [id]: !current }));

  const industryNeedle = industryFind.trim().toLowerCase();
  const sectorIndustries = (activeSectors.length ? industries.filter((entry) => activeSectors.includes(entry.sector)) : industries)
    .map((entry) => ({ ...entry, industries: entry.industries.filter((industry) => matches(industryNeedle, industry)) }))
    .filter((entry) => entry.industries.length);

  // What each section shows for the current "find a filter" text.
  const showRatingSection = showRatings && matches(needle, "rating", ...RATINGS);
  const showSectorSection =
    sectors.length > 0 && matches(needle, "sector", "industry", ...sectors, ...industries.flatMap((entry) => entry.industries));
  const groups = RANGE_GROUPS.map((group) => ({
    ...group,
    ranges: group.ranges.filter((range) => (factorModel || !range.factor) && matches(needle, range.label, range.key, group.label)),
  })).filter((group) => group.ranges.length);
  const showStage = factorModel && matches(needle, "stage", "trend", "200-day average", ...STAGES.map((item) => item.value));
  const shownChoices = CHOICES.filter((choice) => matches(needle, choice.label, ...choice.options.map((option) => option.label)));
  const shownToggles = toggles.filter((toggle) => matches(needle, toggle.label));
  const showListing = exchanges && matches(needle, "exchange", "listed", "nse", "bse");
  const showEligibility = showRatings && factorModel && matches(needle, "eligibility");
  const showEvidence = shownChoices.length > 0 || shownToggles.length > 0 || showListing || showEligibility;
  const nothingShown = !showRatingSection && !showSectorSection && !groups.length && !showStage && !showEvidence;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {/* min-w-0 on a phone: the search shares its row with the icon-only
          Filters trigger and the grid's tool buttons, so it takes whatever
          width is left rather than forcing the row to wrap. */}
      <SearchInput
        value={query}
        onChange={setQuery}
        placeholder="Filter by symbol or company…"
        label="Filter by symbol or company"
        pending={pending}
        className="min-w-0 flex-1 sm:min-w-56"
      />
      <PendingMarker pending={pending} />

      {/* Rating is admin-only (lib/ratings.mjs); from `sm` up its chips sit in the bar. */}
      {showRatings ? (
        <div className="hidden flex-wrap items-center gap-1 sm:flex" role="group" aria-label="Filter by rating">
          {RATINGS.map((rating) => (
            <Pill key={rating} active={activeRatings.includes(rating)} onClick={() => toggleValue("rating", rating)}>
              {rating}
            </Pill>
          ))}
        </div>
      ) : null}

      <Sheet>
        <SheetTrigger
          render={
            <Button
              variant="outline"
              className="relative gap-1.5 max-sm:size-9 max-sm:px-0"
              aria-label={activeFilterCount ? `Filters, ${activeFilterCount} active` : "Filters"}
            />
          }
        >
          <SlidersHorizontal className="size-3.5" aria-hidden />
          <span className="hidden sm:inline">Filters</span>
          {activeFilterCount ? (
            <span className="tabular ml-0.5 rounded-full bg-primary px-1.5 text-[10px] font-semibold text-primary-foreground max-sm:absolute max-sm:-top-1 max-sm:-right-1 max-sm:ml-0 max-sm:min-w-4 max-sm:leading-4">
              {activeFilterCount}
            </span>
          ) : null}
        </SheetTrigger>

        <SheetContent
          side="right"
          className="gap-0 p-0 data-[side=right]:w-[calc(100%-1rem)] data-[side=right]:sm:max-w-md"
        >
          <header className="space-y-3 border-b border-border/70 px-5 pt-4 pb-3">
            <div className="flex min-h-8 items-center gap-2 pr-9">
              <SheetTitle className="text-base font-semibold">Filters</SheetTitle>
              {activeFilterCount ? (
                <span className="tabular rounded-full bg-primary px-1.5 text-[11px] font-semibold text-primary-foreground">
                  {activeFilterCount}
                </span>
              ) : null}
              <span className="flex-1" />
              {activeFilterCount || query ? (
                <Button variant="ghost" size="sm" className="gap-1" onClick={clearAll}>
                  <X className="size-3.5" aria-hidden />
                  Clear all
                </Button>
              ) : null}
            </div>
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <Input
                type="search"
                value={find}
                onChange={(event) => setFind(event.target.value)}
                placeholder="Find a filter: P/E, ROE, industry…"
                aria-label="Find a filter"
                className="h-9 pl-8 text-sm"
              />
            </div>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5">
            {showRatingSection ? (
              <Section title="Rating" count={activeRatings.length} open={isOpen("rating", activeRatings.length)} onToggle={() => flip("rating", isOpen("rating", activeRatings.length))}>
                <div className="flex flex-wrap gap-1.5">
                  {RATINGS.map((rating) => (
                    <Pill key={rating} active={activeRatings.includes(rating)} onClick={() => toggleValue("rating", rating)}>
                      {rating}
                    </Pill>
                  ))}
                </div>
              </Section>
            ) : null}

            {showSectorSection
              ? (() => {
                  const count = activeSectors.length + activeIndustries.length;
                  const open = isOpen("sector", count, true);
                  return (
                    <Section title="Sector and industry" count={count} open={open} onToggle={() => flip("sector", open)}>
                      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Sector">
                        {sectors.map((sector) => (
                          <Pill key={sector} active={activeSectors.includes(sector)} onClick={() => toggleValue("sector", sector)}>
                            {sector}
                          </Pill>
                        ))}
                      </div>
                      {industries.length ? (
                        <div className="space-y-2">
                          <div className="flex items-baseline justify-between gap-2">
                            <span className="text-sm">Industry</span>
                            <span className="text-[11px] text-muted-foreground">
                              {activeSectors.length ? "Within the sectors picked" : "Every sector"}
                            </span>
                          </div>
                          <Input
                            type="search"
                            value={industryFind}
                            onChange={(event) => setIndustryFind(event.target.value)}
                            placeholder="Search industries…"
                            aria-label="Search industries"
                            className="h-8 text-sm"
                          />
                          <div className="max-h-64 space-y-3 overflow-y-auto overscroll-contain rounded-md border border-border/70 p-2.5">
                            {sectorIndustries.length ? (
                              sectorIndustries.map((entry) => (
                                <div key={entry.sector} className="space-y-1.5" role="group" aria-label={`${entry.sector} industries`}>
                                  <p className="text-[11px] font-medium text-muted-foreground">{entry.sector}</p>
                                  {entry.industries.map((industry) => {
                                    const id = `industry-${entry.sector}-${industry}`;
                                    return (
                                      <div key={industry} className="flex items-center gap-2">
                                        <Checkbox
                                          id={id}
                                          checked={activeIndustries.includes(industry)}
                                          onCheckedChange={() => toggleValue("industry", industry)}
                                        />
                                        <Label htmlFor={id} className="cursor-pointer text-sm font-normal">
                                          {industry}
                                        </Label>
                                      </div>
                                    );
                                  })}
                                </div>
                              ))
                            ) : (
                              <p className="py-2 text-center text-xs text-muted-foreground">No industry matches “{industryFind}”.</p>
                            )}
                          </div>
                        </div>
                      ) : null}
                    </Section>
                  );
                })()
              : null}

            {groups.map((group) => {
              const count = group.ranges.filter((range) => ranges[range.key]).length;
              const open = isOpen(group.id, count, group.id === "size");
              return (
                <Section key={group.id} title={group.label} count={count} open={open} onToggle={() => flip(group.id, open)}>
                  {group.ranges.map((range) => (
                    <RangeRow
                      key={range.key}
                      range={range}
                      value={ranges[range.key]}
                      unit={range.size ? sizeSuffix : range.unit === "P" ? "pctl" : range.unit}
                      onChange={(next) => setRange(range, next)}
                    />
                  ))}
                </Section>
              );
            })}

            {showStage
              ? (() => {
                  const open = isOpen("stage", stageCount);
                  return (
                    <Section title="Stage and trend" count={stageCount} open={open} onToggle={() => flip("stage", open)}>
                      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Stage">
                        {STAGES.map((item) => (
                          <Pill key={item.value} active={searchParams.getAll("stage").includes(item.value)} onClick={() => toggleValue("stage", item.value)}>
                            <span title={item.meaning}>{item.value}</span>
                          </Pill>
                        ))}
                      </div>
                      {FACTOR_TOGGLES.map((toggle) => (
                        <FlagRow
                          key={toggle.key}
                          id={toggle.key}
                          label={toggle.label}
                          hint={publicText(showRatings, toggle.hint)}
                          checked={on(toggle.key)}
                          onChange={() => toggleFlag(toggle.key)}
                        />
                      ))}
                      <p className="text-[11px] leading-snug text-muted-foreground">
                        Stage and RS are context: they never change a factor score. S2 Candidate is a Stage 2
                        structure pulled back under its 50-day average.
                      </p>
                    </Section>
                  );
                })()
              : null}

            {showEvidence
              ? (() => {
                  const open = isOpen("evidence", evidenceCount);
                  return (
                    <Section title="Listing and evidence" count={evidenceCount} open={open} onToggle={() => flip("evidence", open)}>
                      {showListing ? (
                        <div className="space-y-1.5">
                          <span className="text-sm">Exchange</span>
                          <div className="flex flex-wrap gap-1.5">
                            {LISTINGS.map((item) => (
                              <Pill key={item.value} active={searchParams.getAll("listing").includes(item.value)} onClick={() => toggleValue("listing", item.value)}>
                                {item.label}
                              </Pill>
                            ))}
                          </div>
                        </div>
                      ) : null}
                      {shownChoices.map((choice) => (
                        <div key={choice.key} className="space-y-1.5">
                          <span className="text-sm">{choice.label}</span>
                          <div className="flex flex-wrap gap-1.5" role="group" aria-label={choice.label}>
                            {choice.options.map((option) => (
                              <Pill key={option.value} active={searchParams.getAll(choice.key).includes(option.value)} onClick={() => toggleValue(choice.key, option.value)}>
                                {option.label}
                              </Pill>
                            ))}
                          </div>
                        </div>
                      ))}
                      {shownToggles.map((toggle) => (
                        <FlagRow
                          key={toggle.key}
                          id={toggle.key}
                          label={toggle.label}
                          hint={publicText(showRatings, toggle.hint)}
                          checked={on(toggle.key)}
                          onChange={() => toggleFlag(toggle.key)}
                        />
                      ))}
                      {showEligibility ? (
                        <div className="space-y-1.5">
                          <span className="text-sm">Eligibility</span>
                          {ELIGIBILITY_CLASSES.map((item) => (
                            <div key={item.value} className="flex items-start gap-2">
                              <Checkbox
                                id={`eligibility-${item.value}`}
                                checked={searchParams.getAll("eligibility").includes(String(item.value))}
                                onCheckedChange={() => toggleValue("eligibility", String(item.value))}
                              />
                              <Label htmlFor={`eligibility-${item.value}`} className="cursor-pointer text-xs leading-snug font-normal">
                                {item.label}
                              </Label>
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </Section>
                  );
                })()
              : null}

            {nothingShown ? (
              <p className="py-10 text-center text-sm text-muted-foreground">No filter matches “{find}”.</p>
            ) : null}
          </div>

          <footer className="flex items-center gap-3 border-t border-border/70 px-5 py-3">
            <p className="flex-1 text-xs text-muted-foreground" aria-live="polite">
              {pending ? "Updating the list…" : "Each change applies as you make it."}
            </p>
            <SheetClose render={<Button size="sm" />}>Show results</SheetClose>
          </footer>
        </SheetContent>
      </Sheet>

      {activeFilterCount || query ? (
        <Button variant="ghost" className="hidden gap-1 sm:inline-flex" onClick={clearAll}>
          <X className="size-3.5" aria-hidden />
          Clear
        </Button>
      ) : null}
    </div>
  );
}
