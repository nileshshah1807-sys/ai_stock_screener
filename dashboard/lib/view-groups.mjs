// How the Views menu is laid out: built-in views under a few headings, in this order, and what
// its button says. The views themselves are data in lib/presets.ts.

/** Headings of the Views menu, in order. A view names one in its `group`. */
export const VIEW_GROUPS = ["Score", "Ratings", "Ownership and flows", "Results and fundamentals", "Size"];

/**
 * The views under each heading, headings in VIEW_GROUPS order and empty ones left out; a view
 * whose group is not listed goes under a last "More" heading rather than vanishing.
 * @template {{ group?: string }} T
 * @param {readonly T[]} views
 * @returns {{ group: string, views: T[] }[]}
 */
export function groupViews(views) {
  const known = new Set(VIEW_GROUPS);
  return [...VIEW_GROUPS, "More"]
    .map((group) => ({
      group,
      views: views.filter((view) => (group === "More" ? !known.has(view.group ?? "") : view.group === group)),
    }))
    .filter((entry) => entry.views.length);
}

/**
 * The Views button's text: the one view that is on, by name, else "Views" (a count badge
 * says how many when several are on).
 * @param {string[]} activeLabels
 */
export function viewsButtonLabel(activeLabels) {
  return activeLabels.length === 1 ? activeLabels[0] : "Views";
}
