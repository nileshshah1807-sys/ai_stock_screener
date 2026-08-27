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
};

export const PRESETS: readonly Preset[] = [
  {
    id: "clears-every-gate",
    label: "Clears every gate",
    description:
      "Eligibility class 0: no BUY or STRONG BUY gate fired at all. The published rating is the model's own view, not a ceiling.",
    query: "eligibility=0&sort=research_score&dir=desc",
    factorOnly: true,
  },
  {
    id: "actionable-buy",
    label: "Actionable BUY",
    description:
      "Rated BUY or STRONG BUY, passing the BUY gates, and executable at the configured target position and participation rate.",
    query:
      "rating=STRONG+BUY&rating=BUY&buyEligible=1&actionable=1&sort=final_score&dir=desc",
  },
  {
    id: "quality-momentum-leaders",
    label: "Quality + momentum leaders",
    description:
      "Quality and momentum both in the top 30% of the cross-section. A relative view: it says nothing about whether the market itself is cheap.",
    query:
      "minQuality=70&minMomentum=70&sort=research_score&dir=desc",
    factorOnly: true,
  },
  {
    id: "uncapped-conviction",
    label: "Uncapped conviction",
    description:
      "Score of 60 or better with no policy ceiling applied, so the score and the rating agree with each other.",
    query: "minScore=60&excludeCapped=1&sort=final_score&dir=desc",
  },
];

/** Keys a view owns. Anything else in the URL is left alone when one is applied. */
const VIEW_KEYS = [
  "q",
  "rating",
  "sector",
  "minScore",
  "maxScore",
  "actionable",
  "buyEligible",
  "excludeCapped",
  "transcript",
  "redFlags",
  "minQuality",
  "minMomentum",
  "eligibility",
  "aboveMa200",
  "sort",
  "dir",
  "cols",
  "density",
] as const;

/**
 * Replace the current view with `query`, preserving nothing but the path.
 *
 * Applying a view has to *clear* the keys it does not set, or a preset would
 * silently inherit whatever filters happened to be active and show a different
 * result set to two people who clicked the same chip. `page` goes too: page 7
 * of the previous result set is meaningless here.
 */
export function applyView(query: string): URLSearchParams {
  const next = new URLSearchParams(query);
  next.delete("page");
  return next;
}

/**
 * True when the current URL already *is* this view.
 *
 * Compared as sorted key/value multisets rather than as strings, because
 * `rating=BUY&rating=STRONG+BUY` and the reverse order are the same view and a
 * string comparison would call them different. Extra params in the URL make it
 * not a match: the chip claims the screen shows exactly the preset, so an added
 * sector filter must switch it off rather than leave it lit misleadingly.
 */
export function viewIsActive(
  current: URLSearchParams,
  query: string,
): boolean {
  const canonical = (params: URLSearchParams) => {
    const pairs: string[] = [];
    for (const [key, value] of params.entries()) {
      if (key === "page") continue;
      if (!(VIEW_KEYS as readonly string[]).includes(key)) continue;
      if (value === "") continue;
      pairs.push(`${key}=${value}`);
    }
    return pairs.sort().join("&");
  };
  return canonical(current) === canonical(new URLSearchParams(query));
}

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
