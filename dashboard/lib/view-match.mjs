/**
 * Whether the screen still shows a named view.
 *
 * Narrowing a view does not switch it off. This used to require an exact
 * match, on the reasoning that the chip claims the screen shows exactly the
 * preset. In practice the rating pills sit beside the view chips and write the
 * same `rating` key, so clicking STRONG BUY on top of a view silently unlit
 * that view while its filters were plainly still in force -- the screen showed
 * both applied and only one of them lit.
 *
 * Every active filter is listed in the FILTERING row directly underneath, so a
 * lit chip plus a visible extra cannot be mistaken for the bare preset. A view
 * still goes dark when one of *its own* filters is removed or changed,
 * including its sort, so the chip keeps meaning "this view's filters are what
 * you are looking at".
 */

import { RANGE_KEYS } from "./screener-ranges.mjs";

/** Keys a view owns. Anything else in the URL is left alone when one is applied. */
export const VIEW_KEYS = [
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
  "eligibility",
  "industry",
  "board",
  "liq",
  "dcf",
  "guide",
  "listing",
  ...RANGE_KEYS,
  "aboveMa200",
  "stage",
  "sort",
  "dir",
  // The viewer's own score mix (lib/custom-score.mjs): a view can be just that.
  "w",
  "cols",
  "density",
];

/**
 * The view-owned pairs of a URL, sorted.
 *
 * A multiset rather than a string, because `rating=BUY&rating=STRONG+BUY` and
 * the reverse order are the same view and a string comparison would call them
 * different.
 */
function canonical(params) {
  const pairs = [];
  for (const [key, value] of params.entries()) {
    if (key === "page") continue;
    if (!VIEW_KEYS.includes(key)) continue;
    if (value === "") continue;
    pairs.push(`${key}=${value}`);
  }
  return pairs.sort();
}

export function viewIsActive(current, query) {
  const wanted = canonical(new URLSearchParams(query));
  if (!wanted.length) return false;

  // Multiset containment: every pair the view sets must still be present, and
  // a view asking for two ratings is not satisfied by only one of them.
  const remaining = canonical(current);
  for (const pair of wanted) {
    const at = remaining.indexOf(pair);
    if (at === -1) return false;
    remaining.splice(at, 1);
  }
  return true;
}

/**
 * `current` with a view added on top: each key the view sets takes the view's
 * values, and every other filter stays. Views combine, so a size floor and a
 * saved mix can be on at once.
 * @param {URLSearchParams} current
 * @param {string} query
 */
export function applyView(current, query) {
  const next = new URLSearchParams(current.toString());
  const view = new URLSearchParams(query);
  for (const key of new Set(view.keys())) {
    next.delete(key);
    for (const value of view.getAll(key)) next.append(key, value);
  }
  next.delete("page");
  return next;
}

/**
 * `current` without the pairs a view set: the other way of tapping its chip.
 * @param {URLSearchParams} current
 * @param {string} query
 */
export function removeView(current, query) {
  const next = new URLSearchParams(current.toString());
  const view = new URLSearchParams(query);
  for (const key of new Set(view.keys())) {
    const drop = view.getAll(key);
    const kept = next.getAll(key).filter((value) => !drop.includes(value));
    next.delete(key);
    for (const value of kept) next.append(key, value);
  }
  next.delete("page");
  return next;
}
