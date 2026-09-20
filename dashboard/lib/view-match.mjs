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
  "minQuality",
  "minMomentum",
  "eligibility",
  "aboveMa200",
  "stage",
  "minRs",
  "sort",
  "dir",
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
