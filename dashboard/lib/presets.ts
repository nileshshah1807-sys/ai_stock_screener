/**
 * Built-in screener views.
 *
 * A view is a query string and nothing else. That is only possible because
 * `parseFilters` and `toSearchParams` already round-trip the entire screen --
 * filters, sort, hidden columns and density -- through the URL, so a preset
 * needs no storage, no server state and no migration when a filter is added.
 *
 * Each one answers a question the model is actually able to answer, rather than
 * being a decorative shortcut. `sort` is set explicitly where the default rank
 * would bury the thing the view is about.
 */

import type { MarketCode } from "@/lib/markets";
import { VIEW_KEYS, applyView, litViews, removeView, viewIsActive } from "@/lib/view-match.mjs";

// Re-exported so callers keep importing view state from one place.
export { applyView, litViews, removeView, viewIsActive };

export type Preset = {
  id: string;
  label: string;
  /** Shown in the tooltip. Says what the view selects and what it does not. */
  description: string;
  query: string;
  /**
   * Model 5.0 only. Hidden on a 4.x run for the same reason the factor filter
   * controls are: those columns are null there and PostgREST comparisons
   * exclude nulls, so the preset would empty the grid rather than do nothing.
   */
  factorOnly?: boolean;
  /** Shown only in this market: the view is stated in its currency units. */
  market?: MarketCode;
  /** Its heading in the Views menu: one of VIEW_GROUPS (lib/view-groups.mjs). */
  group: string;
};

export const PRESETS: readonly Preset[] = [
  {
    // The owner's own mix (saved as "GOAT", 22 Nov 2026): a third on the latest earnings call,
    // the rest spread over the five factor blocks. A score mix only: it filters nothing.
    id: "cupel-blend",
    group: "Score",
    label: "Cupel blend",
    description:
      "Every stock ranked by Cupel's own mix: earnings call 33%, momentum 20%, quality 17%, growth 17%, value 10%, steadiness 3%.",
    query: "sort=custom_score&w=q25.g25.m30.v15.r5.c50",
    factorOnly: true,
  },
  {
    id: "clears-every-gate",
    group: "Ratings",
    label: "Clears every gate",
    description:
      "Eligibility class 0: no BUY or STRONG BUY gate fired at all. The published rating is the model's own view, not a ceiling.",
    query: "eligibility=0&sort=research_score&dir=desc",
    factorOnly: true,
  },
  {
    id: "actionable-buy",
    group: "Ratings",
    label: "Actionable BUY",
    description:
      "Rated BUY or STRONG BUY, passing the BUY gates, and executable at the configured target position and participation rate.",
    query:
      "rating=STRONG+BUY&rating=BUY&buyEligible=1&actionable=1&sort=final_score&dir=desc",
  },
  {
    id: "quality-momentum-leaders",
    group: "Ratings",
    label: "Quality + momentum leaders",
    description:
      "Quality and momentum both in the top 30% of the cross-section. A relative view: it says nothing about whether the market itself is cheap.",
    query:
      "pq=70~&pm=70~&sort=research_score&dir=desc",
    factorOnly: true,
  },
  {
    id: "uncapped-conviction",
    group: "Ratings",
    label: "Uncapped conviction",
    description:
      "Score of 60 or better with no policy ceiling applied, so the score and the rating agree with each other.",
    query: "minScore=60&excludeCapped=1&sort=final_score&dir=desc",
  },
  {
    id: "fresh-stage-2",
    group: "Ratings",
    label: "Fresh Stage 2 leaders",
    description:
      "Score 70+, in Stage 2 with an RS rating of 70+, most recent stage entry first. Context, not a signal: blending stage into the rank lowered returns in every validation window (P3), so this narrows the list without evidence that it improves it.",
    query: "minScore=70&stage=Stage+2&rs=70~&sort=stage2_entry_date&dir=desc",
    factorOnly: true,
  },
  {
    id: "above-1000-cr",
    group: "Size",
    label: "≥ ₹1,000 Cr",
    description:
      "Companies of ₹1,000 Cr or more of market cap. A narrower list, not a better one: on the backtest the smaller names earned more, with more single-stock blow-ups and higher trading costs.",
    query: "cap=1000~",
    market: "NSE",
  },
  {
    id: "institutions-accumulating",
    group: "Ownership and flows",
    label: "FII + DII buying",
    description:
      "FII and DII holdings both above the previous quarter's in the latest shareholding pattern.",
    query: "fiich=0.01~&diich=0.01~",
    market: "NSE",
  },
  {
    id: "foreign-tailwind",
    group: "Ownership and flows",
    label: "Foreign tailwind",
    description:
      "FPI buying in the stock's sector ran above its six-month average in NSDL's latest fortnight, and FII holding is above the previous quarter's.",
    query: "sfpi=0~&fiich=0.01~",
    market: "NSE",
  },
  {
    id: "promoters-adding",
    group: "Ownership and flows",
    label: "Promoters adding",
    description: "Promoter holding above the previous quarter's in the latest shareholding pattern.",
    query: "promoterch=0.01~",
    market: "NSE",
  },
  {
    id: "under-owned-quality",
    group: "Ownership and flows",
    label: "Under-owned quality",
    description:
      "FII and DII holdings each under 2%, return on equity 15% or more, debt under half of equity, ₹500 Cr or more of market cap.",
    query: "fii=~2&dii=~2&roe=15~&de=~0.5&cap=500~",
    market: "NSE",
  },
  {
    id: "guidance-raised",
    group: "Results and fundamentals",
    label: "Guidance raised",
    description: "Management raised guidance on the latest earnings call, and profit grew 15% or more year on year.",
    query: "guide=raised&epsg=15~",
  },
  {
    id: "results-this-week",
    group: "Results and fundamentals",
    label: "Results this week",
    description: "Companies whose announced results date falls in the next seven days.",
    query: "dtr=0~7",
  },
  {
    id: "margin-expansion",
    group: "Results and fundamentals",
    label: "Margin expansion",
    description:
      "Operating margin in the latest filed quarter above the same quarter a year earlier, and revenue up 10% or more year on year.",
    query: "opmch=0.01~&revg=10~",
    market: "NSE",
  },
  {
    id: "foreign-funds-buying",
    group: "Ownership and flows",
    label: "Foreign funds buying",
    description: "Foreign funds bought more than they sold in bulk and block deals over the last month.",
    query: "fdeals=0.01~",
    market: "NSE",
  },
];

export type SavedView = { id: string; label: string; query: string };

export const SAVED_VIEWS_STORAGE_KEY = "screener.savedViews.v1";

/**
 * Saved views as an external store, read through `useSyncExternalStore`.
 *
 * localStorage is exactly what that hook is for, and the alternative -- reading
 * it in an effect and calling setState -- produces a cascading render on every
 * mount and cannot represent "not yet known" during hydration. Going through
 * the store also makes a second tab's edit show up here, which the effect
 * version silently would not.
 *
 * The snapshot must be referentially stable or the hook re-renders forever, so
 * the parse is memoised against the raw string.
 */
const NO_VIEWS: SavedView[] = [];
const listeners = new Set<() => void>();

let cachedRaw: string | null = null;
let cachedViews: SavedView[] = NO_VIEWS;
let subscribed = false;

/**
 * Parse stored JSON into views, discarding anything malformed.
 *
 * Tolerant by design: this is browser storage that a future version, another
 * tab, or a curious user can leave in any state. A bad blob yields an empty
 * list rather than throwing inside a render and taking the screener down with
 * it.
 */
function parseSavedViews(raw: string): SavedView[] {
  if (!raw) return NO_VIEWS;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return NO_VIEWS;
    const views = parsed.flatMap((item): SavedView[] => {
      if (typeof item !== "object" || item === null) return [];
      const { id, label, query } = item as Record<string, unknown>;
      if (typeof id !== "string" || typeof label !== "string") return [];
      if (typeof query !== "string") return [];
      return [{ id, label, query }];
    });
    return views.length ? views : NO_VIEWS;
  } catch {
    return NO_VIEWS;
  }
}

function emit(): void {
  for (const listener of listeners) listener();
}

export function subscribeSavedViews(listener: () => void): () => void {
  listeners.add(listener);
  // `storage` fires in *other* tabs only, so a write in this one calls emit()
  // directly. One shared window listener rather than one per subscriber.
  if (!subscribed && typeof window !== "undefined") {
    subscribed = true;
    window.addEventListener("storage", (event) => {
      if (event.key === null || event.key === SAVED_VIEWS_STORAGE_KEY) emit();
    });
  }
  return () => {
    listeners.delete(listener);
  };
}

export function savedViewsSnapshot(): SavedView[] {
  if (typeof window === "undefined") return NO_VIEWS;
  let raw = "";
  try {
    raw = window.localStorage.getItem(SAVED_VIEWS_STORAGE_KEY) ?? "";
  } catch {
    return NO_VIEWS;
  }
  if (raw === cachedRaw) return cachedViews;
  cachedRaw = raw;
  cachedViews = parseSavedViews(raw);
  return cachedViews;
}

/** The server has no localStorage, so the first paint has no saved views. */
export function savedViewsServerSnapshot(): SavedView[] {
  return NO_VIEWS;
}

export function writeSavedViews(views: SavedView[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      SAVED_VIEWS_STORAGE_KEY,
      JSON.stringify(views),
    );
  } catch {
    // Private-browsing quota failures are not worth interrupting a screen for.
    // The view stays applied in the URL, which is the shareable artefact.
  }
  emit();
}

/** The current URL reduced to the keys a view owns. */
export function currentViewQuery(params: URLSearchParams): string {
  const next = new URLSearchParams();
  for (const key of VIEW_KEYS) {
    for (const value of params.getAll(key)) {
      if (value) next.append(key, value);
    }
  }
  return next.toString();
}
