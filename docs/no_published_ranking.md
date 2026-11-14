# No published ranking: "Your score" replaces the model's rank

Branch `feat/hide-rank-nonadmin` (8 commits on top of `main` at `f0b36c7`), deployed to the
preview Worker `cupel-preview` only. Production (`main`, `cupel.in`) is unchanged.

## Why

Cupel is a paid product. Under SEBI's Research Analyst Regulations (as amended December
2024), a paid list that orders stocks by the provider's own assessment is a research
service, whatever it is called and whatever disclaimer sits beside it. A rank or a single
0-100 "score" is that assessment in another form, and the order alone tells a reader which
stock the model prefers. A disclaimer or an "educational purposes only" label does not
change this. Until Cupel is registered, or partners with someone who is:

- **We publish evidence, not a verdict.** Factor scores, percentiles, prices, stage,
  valuation and concall readings each describe a stock on one measure. They stay.
- **No viewer sees the model's rank or score, admins included.** The buy/sell ratings were
  already admin-only, and they stay that way.
- **Each viewer ranks by their own method.** "Your score" lets the viewer pick the weights,
  and Cupel ships no preset that copies the model.

See also [`commercialisation_readiness.md`](commercialisation_readiness.md).

## What changed for the user

| Area | Before | After |
|---|---|---|
| Screener columns | `#` (rank), Score, Fundamental, Technical | Removed for everyone; "Your score" column appears when a mix is set |
| Default sort | By rank (`investment_rank`) | By market cap; by "Your score" when a mix is set |
| Stock page | Rank and Score tiles, Published score ring, score waterfall, rank history, audit scores | Removed; the panel is now "Factor profile" (percentiles on each measure) |
| Movers page | Rank changes, admin-only | Returns "not found"; removed from the nav |
| Rank badges | On the Home and Market movers lists | Removed |
| Filters | "Minimum decision score" | Removed |
| Presets | Some sorted by research or final score | Hidden for everyone |
| Results/Concalls filters | "Score" rule | Removed |
| Search | Showed rank and score | Neither; ordered by size |
| CSV export | Rank and score columns | Removed (an admin keeps the rating columns) |
| Screener intro | "ranked daily on ..." | "measured daily on ... Rank them by your own score." |
| Saved views | A view with only a score mix said "Nothing to save" | The mix (`w=`) is saved with the view |
| Filters | A popover: sector, stage, two factor floors; market cap only as a view, and picking a view dropped the others | A side panel with a "find a filter" box: sector and industry, market cap, turnover, P/E, P/B, yield, ROE, ROIC, debt to equity, growth, returns, RSI, volatility, drawdown, factor percentiles, board, liquidity, reverse DCF and concall guidance. Each is a `key=min~max` URL pair, so views and links carry them, and views now combine |

## "Your score": how it is calculated

`dashboard/lib/custom-score.mjs`. The mix lives in the URL (`w=q25.g25.m30.v15.r5.d10.c100`),
so it can be shared and saved as a view.

1. **Weights** over the five factor block scores (Quality, Growth, Momentum, Value, Risk),
   plus RS rating and concall tone. A missing block counts as 50, never 0.
2. **The blend is ranked across the whole run** onto a 0-100 scale, ties averaged. This is
   the same transform the model applies to its research score. Filters narrow the list but
   never change anyone's score.
3. **Optional points** are added after that ranking:
   - `d`, valuation points: `d/100` per point the DCF valuation score sits from 50, where
     the run marked the DCF eligible.
   - `c`, concall points: `c/100` per point a call from the last 180 days sits from the
     run's median call. The call is read as 85% outlook (from `concall_feed`) and 15% tone,
     and counts half as much every 90 days. With fewer than 30 calls, the reference is 50
     instead of the median.

The builder starts from equal weights and ships no other preset. A score can exceed 100
once points are added; the order is unaffected.

**Why build it this way:** these are the same building blocks the model uses, so a viewer
can reproduce the method if they choose. We measured this on the 13 Nov 2026 NSE run with
weights `q25 g25 m30 v15 r5`, valuation ×0.10 and concall ×1.00. The result matched
production's `Investment_Rank` with a 0.997 rank correlation, 8 of the top 10, 21 of the
top 25 and 84 of the top 100. The rest of the gap is mostly the policy gates. For example,
MATRIMONY is #2 here and #149 in production. The gates are rating fields and stay hidden.
Those weights are the owner's own and are not shipped.

**Not modelled:** the taper that reduces a call's weight near a quarter's turn (a
`shortcut:` comment marks it). The outlook comes from the Concalls feed and can differ
from the run's for a few names.

## What changed in the code

| File | Change and reason |
|---|---|
| `dashboard/lib/ratings.mjs` | `VERDICT_KEY` / `isVerdictField` name the verdict: rank, final/evidence/decision/research score, block blends, `*_weight`, rank and score changes. `withoutVerdict` strips them for an admin, and `withoutRatings` strips ratings and verdict for a viewer. `SHOW_VERDICT = false` is the one switch back. `usesVerdict` hides presets that sort by the verdict. |
| `dashboard/lib/queries.ts` | `forViewer` redacts on the server, so the numbers never reach the browser. A verdict sort or a minimum-score filter is refused for everyone. The default sort is market cap. `runScores` reads the whole run (columns every viewer can already see) plus the latest outlooks, and ranks by "Your score". The search index carries no rank or score. Company facts no longer read the score. |
| `dashboard/lib/custom-score.mjs` (new) | The score: `parseWeights`, `formatWeights`, `weightedScore`, `scoreRun`, `rankScores`, `concallRecency`. |
| `dashboard/components/screener/score-builder.tsx` (new) | The "Your score" popover, with weight sliders and point sliders. |
| `dashboard/lib/columns.ts` | `VERDICT_COLUMNS` (hidden from everyone) and `ADMIN_ONLY_COLUMNS` (plus the rating); the "Your score" column. |
| `screener-table.tsx`, `screener-rows.tsx`, `view-options.tsx` | Hide the verdict columns; show "Your score" when a mix is set. |
| `filter-bar.tsx`, `saved-views.tsx`, `lib/event-filters.mjs` | Remove the score filter, the verdict-sorted presets and the feed's Score rule. |
| `app/(app)/[market]/stocks/[symbol]/page.tsx`, `components/stock/factor-blocks.tsx` | Verdict panels gated on `SHOW_VERDICT`; weights and points no longer shown. |
| `app/(app)/[market]/movers/page.tsx`, `components/app-shell.tsx`, `movers-body.tsx`, `live-movers.tsx` | Movers page "not found", removed from the nav, no rank chips. |
| `app/api/export/route.ts` | The CSV drops the verdict columns, for admins too. |
| `lib/filters.ts`, the screener/watchlists/indices/market pages | Default sort is market cap (`custom_score` when `w` is set). |
| `lib/screener-intro.mjs` | "measured", not "ranked". |
| `lib/view-match.mjs` | `w` and every filter key are part of a saved view; `applyView` merges a view in and `removeView` takes it off. |
| `lib/screener-ranges.mjs` (new), `filter-bar.tsx`, `active-filters.tsx` | Every numeric filter as data (column, unit, presets), read by the panel, the chips and the query. Old keys (`minCapCr`, `minQuality`, `minMomentum`, `minRs`) still work as a minimum. |
| `dashboard/wrangler.preview.jsonc` | `keep_vars` and `keep_names: false`, so a deploy does not wipe the preview Worker's settings. |
| `scripts/smoke-check.mjs` | No longer visits `/movers`. |
| `README.md`, `dashboard/README.md`, `CLAUDE.md` | Document the rule and how "Your score" works, and tell future work not to bring the verdict back. |

Tests: `custom-score.test.mjs` (new), plus additions to `ratings.test.mjs` and
`view-match.test.mjs`. The full suite is 509 passing; typecheck and lint are clean.

## What did not change

- **The daily screener** still computes and publishes everything, the rank and score
  included. The dashboard reads its factor, valuation and concall columns. The rank and
  score are kept for the Returns backtest and for restoring later. Nothing in `screener/`
  changed.
- **Buy/sell ratings** stay admin-only, as before.
- **The database views** (`*_visible`) still return the rank and score to a signed-in user
  who queries them directly with their own token. Only the app hides them, so this is
  accepted **for the preview only and blocks production**. Two ways to close it: add the
  verdict fields to `is_rating_field` in `storage/rating_access_schema.sql` and re-apply it
  by hand (this changes the shared database, so the live site at once, and every read that
  tells rated from unrated by `investment_rank is not null` must first move to another
  test), or ship after the D1 move, where the browser cannot query the database at all and
  the server picks the verdict columns for no one.

## Known limits and follow-ups

- **Admin view not checked on the preview:** the browser used for testing was signed in as
  a viewer.
- **The `live_market` RPC** sends `rated` instead of `investment_rank` in
  `storage/live_quotes_schema.sql`, which must be re-applied by hand **after** this branch
  is live: the code on `main` still reads the rank from it. Until then the browser falls
  back to the rank (`liveMover` in `lib/live-quotes.mjs`) and drops it before any component
  sees it, but the rank is still in the network response. The Home monthly movers and a new
  listing's page no longer carry or show a rank or score.
- **The daily email report** lists ranks. That is fine if it reaches only the owner, but
  not if it reaches any customer.
- **Speed:** a page sorted by "Your score" reads the whole run on each request. This has not
  been measured.
- **Dead code:** `movers/loading.tsx` and `getMovers` are left unused.
- **Graphify:** the graph was updated for code only, in the branch worktree. Doc changes and
  the 118 regrouped communities need a full `/graphify --update`.

## How to bring the ranking back (after registration)

Set `SHOW_VERDICT = true` in `dashboard/lib/ratings.mjs`. This brings back to admins the
rank and score data and sorting, the stock page panels and the CSV columns. Showing it to
viewers as well, and restoring the Movers page, nav item, rank chips, presets, score filter
and Score rule, means reverting `0c2783a`.

## Deployment

| | |
|---|---|
| Preview | `https://cupel-preview.chirayu21-shah03.workers.dev` (Worker `cupel-preview`, its own cache prefix, Razorpay test keys, `APP_ENV` unset) |
| Production | Not deployed; `main` not changed; branch not pushed |
| Env mapping (names only) | `CLOUDFARE_TOKEN` → `CLOUDFLARE_API_TOKEN`, `CLOOUDFARE_ACCOUNT_ID` → `CLOUDFLARE_ACCOUNT_ID`, `SUPABASE_URL` → `NEXT_PUBLIC_SUPABASE_URL`; `NEXT_PUBLIC_SUPABASE_ANON_KEY` read from the preview Worker's own settings |
