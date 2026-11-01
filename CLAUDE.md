# Winnow — working notes

Daily equity research screener across two markets, NSE and US. `app.py` is the
composition root; the scheduled GitHub Actions workflows are the production
runtime, one per market.

## Commands

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
TRANSCRIPT_ENABLE_FINBERT=false pytest      # 1085 tests, ~35s
ruff check .                                 # must stay clean

MARKET=US python app.py                      # the same pipeline, US universe
```

Tests are `unittest`-style classes run under pytest. `TRANSCRIPT_ENABLE_FINBERT=false`
keeps the FinBERT path — and the torch import behind it — out of the run; CI and
the scheduled workflows set the same flag.

## Conventions

- **Logging, not printing.** Every module does `logger = logging.getLogger(__name__)`.
  `print()` is acceptable only under `tools/`, where console output is the interface.
- **Rounding goes through `screener.numeric`.** Use `round_half_up` /
  `round_series_half_up`, never bare `round()` on an exported number. Python,
  NumPy and pandas disagree at exact half-cent boundaries, and exports must be
  version-stable.
- **Missing vendor values go through `safe_float`** (`screener.numeric`), which
  treats `None`, `NaN` and stray text alike as "not reported".
- **Design: SOLID and DRY, at the codebase's own grain.** One owner per
  decision: the enricher gathers evidence, `screener/recommendation.py`
  weighs it, the publisher ships it. A rule lives in exactly one function
  and every caller asks it, never a copy of its arithmetic (e.g.
  `RecommendationPolicy._outlook_share`). Extend through config and the
  existing seams (`MarketProfile`, a scoring component, a policy method)
  rather than a branch in a caller. Small, single-purpose functions; no
  abstraction for one caller. Before adding a rule, grep for the place that
  already decides it.
- **Absent evidence is not a zero.** Scores are coverage-normalised: a component
  whose input was never reported leaves both the numerator and the denominator,
  and the result is shrunk toward neutral. Never let an unreported metric score
  as the worst observed value.

## Markets

- **`MARKET` selects the market; everything else follows.** `screener/markets.py`
  holds one `MarketProfile` per market — ticker suffix, timezone, session
  cutoff, benchmark index, universe source, currency. A profile supplies
  **defaults only**: every env var keeps its old name and precedence, so an
  unset `MARKET` resolves to exactly the NSE values the pipeline used before it
  was market-aware. That property is what the test suite asserts, and it is why
  adding a market did not disturb the existing one.
- **The scoring layer is market-agnostic and must stay that way.**
  `screener/scoring/`, `factors.py` and `stage.py` are cross-sectional *within
  one run's frame*, so a US run ranks US stocks against US stocks with no
  changes. Never introduce a market branch into a score.
- **Env vars named `*_INR` and `*_IST` are read as market currency and market
  local time.** `MIN_AVG_TURNOVER_INR` is dollars on a US run;
  `MARKET_BAR_COMPLETE_AFTER_IST` is 16:00 ET. The names are kept for
  compatibility with the schema, the publisher and existing workflows, and
  renaming them would cascade for no behavioural gain.
- **`market` is part of every read-model key.** A symbol does not identify a
  company across exchanges — TCS is Tata Consultancy on NSE and The Container
  Store in the US. Any new query against `screener_snapshot` or
  `screener_history` must filter on it, and chart price series live under
  `price-series/{MARKET}/` in Storage; `DashboardRepository` is scoped to one
  market at construction so it cannot be forgotten.
- **US annual statements come from SEC EDGAR; Yahoo is the fallback.**
  `STATEMENT_SOURCE=edgar` (set in the US workflow) makes
  `FinancialStatementCollector` ask `screener/edgar.py` first and Yahoo only
  for what EDGAR cannot serve -- filers reporting in another currency, a ticker
  SEC does not list. EDGAR's facts are rebuilt into Yahoo-shaped frames, so
  `derive_statement_factors` is shared and the scoring layer still has no
  market branch. SEC rejects clients that name no contact: the address lives in
  the `SEC_USER_AGENT` repository variable, and without it the run warns and
  uses Yahoo throughout. Measure the two sources against each other with
  `python -m tools.compare_statement_sources`. Prices and quote metadata
  (`Ticker.info`) are still Yahoo's.
- **NSE quarterly results come from the exchange's filings, stored once; Yahoo
  is the fallback.** `workers/quarterly_filings.py` (the Quarterly filings
  workflow, dispatch-only: cron-job.org calls it every 15 minutes and once a
  day with `full=true`; do not add a `schedule:`, it would double every run)
  is the only job that reads NSE's integrated-filing index and its
  documents. It parses each filing once into `quarterly_filings` (one row
  per symbol, quarter and basis; a revision replaces the row; a
  `PARSER_VERSION` bump re-reads them all) and redraws the Financials tab
  for every company it stored a filing for.
  Four readers, none of which fetches anything itself: the stock page's
  quarterly results (`workers/financial_statements.compose_quarters`: every
  filed quarter from its filing, consolidated where the latest quarter was
  filed so -- unless only the standalone filings reach the year-ago
  quarter, a company just begun to consolidate; the Results page's card
  opens on the same basis; Yahoo only for quarters with no filing, minus any line that
  disagrees with the filing on a shared quarter -- a broker's net revenue,
  pretax profit counting associates); the screener's `Revenue_Growth` and
  `Earnings_Growth` (`screener/quarterly_results.py`, by the backtest's own
  rule, `backtest.fundamentals.QuarterPanel`: both quarters on one basis,
  profit not EPS, no rate on a non-positive base; read only where the run
  has Supabase credentials, so a validation dispatch keeps Yahoo's); and the
  bell's results events. Banks and insurers file a different statement,
  parsed by `FINANCIAL_TAGS` into the page's rows as Yahoo means them (a
  bank's revenue is net interest income plus other income); they are stored
  for the stock page, the Results page and the bell, but the screener keeps
  Yahoo's growth for them (`DISPLAY_ONLY_TAXONOMIES`), as for a company
  with no year-ago filing, and one where Yahoo is already on a later quarter; see `quarter_results_*` in
  the run diagnostics. The fourth is the dashboard's Results page
  (`dashboard/lib/results.ts`), which reads the table as the signed-in
  viewer through the `quarterly_result_feed` view and re-renders every few
  minutes, so a result appears once the worker stores it. The table is in
  `storage/quarterly_filings_schema.sql` and must be applied by hand. Measure the two sources with
  `python -m tools.compare_quarter_growth_sources`. The index begins in
  April 2025; the older endpoint `backtest/filings.py` reads ends that
  January. A filing that states only a half year (MTARTECH, Sep 2026) is stored
  as its quarter, less the earlier quarters on the same basis (`PARSER_VERSION` 4).
  A filing the worker could not store (a fetch the archive refused, or a file format the parser does
  not read -- the latter listed by the full run only) is written to a `filing-attempts` artifact of the
  workflow run (JSON, kept 14 days) with its reason, and counted in the run's summary; no table.
  Annual statements, valuation ratios and prices are still Yahoo's.
- **A company listed on BSE alone is screened in the NSE run as `SYMBOL.BO`.**
  `NSE_UNIVERSE_SOURCE=nse_with_bse_only` (set in the NSE screener and price
  series workflows) adds every mainboard company whose ISIN NSE does not list,
  read from the last five BSE bhavcopies (BSE's APIs refuse scripts and
  headless browsers alike). The symbol is its Yahoo ticker, so it can never
  equal an NSE symbol and `ticker_for` passes it through; `is_bse_only`
  (`screener/markets.py`) is the one test for it. Prices, statements, live
  quotes and charts are Yahoo's; NSE's filings, shareholding, impact cost and
  transcripts have nothing for it and degrade. Its results and shareholding
  filings come from `workers/bse_source.py` (written by the owner; the repo
  itself never fetches from BSE): `workers/bse_filings.py`, a step of the
  Quarterly filings workflow, turns them into NSE index records and stores
  them through `workers.quarterly_filings` and `workers.shareholding`, so every
  reader of those tables shows them. Until a filing is stored, its results
  event is its stored statements gaining a quarter, as in the US. The dashboard shows it as
  `SYMBOL` tagged BSE (`dashboard/lib/listing.mjs`).
  In every market, a session a name did not trade is still a session: Yahoo
  carries the close forward with zero volume and the collector keeps that bar;
  only a name with no volume anywhere in the window is dropped.
- **NSE prices are Yahoo's, with one bar from the bhavcopy when Yahoo lacks it.**
  `PRICE_BAR_FALLBACK_ENABLED` (set in the NSE workflow) lets
  `screener/session_bars.py` fill a symbol's missing expected-session bar from
  NSE's daily file -- only that bar, only when it continues Yahoo's history.
  The patched symbols are listed in the run diagnostics under
  `technical_session_bar_patched_symbols`. There is no US source, so a Yahoo
  gap there still fails the alignment guard.
- **A change of price basis is restated from the bars, in the chart and in
  the screen.** Neither NSE's action feed nor Yahoo can be drawn or scored as
  served: the feed has no ratio for a demerger or a rights issue, quotes ISINs
  the security never traded under, misdates some actions and omits fund unit
  splits; Yahoo adjusts for neither demergers nor rights issues and
  back-adjusts some splits only part of the way. Each leaves a cliff of 30-90%
  that no holder took. Two rules in `backtest/corporate_actions.py` size a
  change from the security's own bars: `ex_date_price_factor` (previous close
  over the ex-date open, for an action the feed names) and `open_gap_factor`
  (an open beyond `MarketProfile.max_open_gap` was not traded to -- NSE caps
  its opening auction at 20%; the US does not, so the rule is off there).
  `workers/price_series_publisher.reconcile_with_prices` applies both to the
  chart and checks every stated ratio against the gap the price actually
  showed. `PRICE_BASIS_RESTATEMENT_ENABLED` (set in the NSE workflow) makes
  `screener/price_basis.py` apply both to Yahoo's adjusted close and drop
  single-session bad prints; see `technical_price_basis_restated_symbols`,
  `technical_bad_print_symbols` and `technical_action_ledger_status` in the
  run diagnostics. All of it is display-grade: the backtest still excludes a
  position that spans a demerger, rights issue or buyback.
- **An action is keyed by ISIN, then ISIN core, then ticker as of the
  ex-date** (`AdjustmentTable.key_for`). Keyed on the feed's ISIN alone, a
  split whose ISIN the archive never saw matches no price row and is silently
  dropped.
- **Notifications are events derived from data other jobs already collect.**
  `workers/market_events.py` (a step in the Quarterly filings and Financial
  statements workflows)
  writes `market_events`, one row per `(market, kind, symbol, event_key)`,
  written once: a `results` event from the stored NSE filings (so the bell
  never announces a quarter the page cannot show), or in the US from
  the stored statements gaining a quarter (no filing index there, so the first
  sighting of a company is a hidden baseline, not an announcement), and a
  `transcript` event from the transcript tables. The dashboard's bell counts
  events recorded after the viewer's `notification_reads.seen_at`, scoped to
  their watchlists when they have any. Display evidence only: nothing scores
  it. A new kind is one function in the worker and one entry in
  `dashboard/lib/notifications.mjs`; the tables are in
  `storage/notifications_schema.sql` and must be applied by hand.
- **An NSE call is read the evening it is held, from its recording; the filed
  transcript replaces it.** A company files its transcript days after the
  call but a "link of recording" notice the same evening. The Earnings call
  recordings workflow (`workers/call_recordings.py`) downloads the audio the
  notice names, cuts it at pauses, transcribes one piece per runner with
  `faster-whisper` (`requirements-speech.txt`, outside the production lock),
  and stores the text as an ordinary transcript whose document's
  `extraction_method` starts `speech:`. Tone, outlook and the screener read
  it unchanged -- no scoring code knows the difference. When the transcript
  worker stores the filed transcript it deletes the recording's
  (`delete_speech_transcripts`): left beside it, the recording would be that
  call's "previous quarter" in `latest_transcript_sentiment`. Half the
  notices name an audio file; `transcripts/recording_sources.py` resolves
  some of the rest -- a shared-drive file, or the one recording of this
  quarter on an investor page, told by its name or, since most are named by
  the conference provider's number, by being the only audio file uploaded in
  the week of the notice. Every page a notice names is tried, the deepest
  first (the home page in its letterhead is a link too), including an
  address printed without `http`. A page that builds its player with a
  script, loads it only when a row is opened, or refuses a plain request is
  opened in the runner's Chrome (`transcripts/page_browser.py`,
  `CALL_RECORDING_BROWSER` in the workflow): what the page labels as a
  call's audio is clicked and the file it then asks for is taken, nothing is
  played, and the site's own investor pages one link in are opened the same
  way. Every rule takes nothing rather than choose between recordings, and a
  file the site says was uploaded more than six days before the notice is
  never taken, whatever it is called. These are rules about pages, not about
  companies: none names a site. A run spends at most
  `browse_seconds_per_run` in the browser and leaves the rest of the
  notices, unmarked, for the next run. A video is never fetched: the video
  site refuses a hosted runner's address (13 Oct 2026).
  No third party's transcript is read: the one vendor that publishes them
  openly was asked and requires a licence (13 Oct 2026). A recording not in
  English, or a call
  with no recording to fetch, waits for the filed transcript. The speech
  text has no speaker labels, so the tone score reads it as one voice -- its
  agreement with the filed transcript's score has not been measured yet.
  `workers/concall_feed.py` derives `concall_feed` (one row per call, no
  text) for the dashboard's Concalls page; the table is in
  `storage/concalls_schema.sql` and must be applied by hand.
- **Management's sentiment on the Concalls page is the outlook score in a
  word.** `workers/concall_feed.management_stance` reads the call's outlook
  score into a band (`sentiment.outlook.stance_from_score`: bullish from 72,
  optimistic 62, neutral 53, cautious 45, bearish below) and quotes the
  scored statement that moved it most that way. The bands sit where the
  stored scores fall -- median 59, 85% above 50 -- because the ranking
  measures a call against the median call, not 50. No request asks for it:
  asked of the model, the label cost more than the outlook (a request of its
  own with thinking on, some 17,000 tokens a call) and moved nothing that
  ranks; asked as a field of the extraction it read most calls neutral; asked
  how upbeat management sounded, nearly all optimistic (14-15 Oct 2026). To
  make the label better, make the outlook score better. Do not label a call
  from the word-list tone score: its risk component counts vocabulary, and
  called a wealth manager "Bearish" for discussing market risk.
- **The outlook model is paid in production and free in development.**
  `sentiment/llm_provider.py` sends the request to OpenRouter in GitHub
  Actions -- and refuses Token Harbor there -- and to Token Harbor's free
  DeepSeek model on a developer's machine, unless `--provider openrouter` or
  `OUTLOOK_PROVIDER` says otherwise; a missing free key is an error, never a
  fall back to the paid one. Local runs read the production Supabase and the
  screener reads the latest outlook of any model, so a Token Harbor reading
  is a trial: printed, never stored. The free allowance is 5M tokens a
  rolling week, about 400 extractions; a spent allowance stops the run
  (`QuotaSpentError`) rather than failing every call after it. One
  exception, by hand: the September 2026 quarter's 247 calls were re-read
  with the October prompt on Token Harbor and stored (29 Oct 2026); their
  `model_name` starts `tokenharbor/`. Two models reading one call rank it
  differently (0.65 Spearman against the stored GLM readings), so the score
  carries the reader as well as the call.
- **Outlook weights score a reading; they are not part of it.** After a
  change to `sentiment.outlook.outlook_items`, run
  `python -m tools.rescore_transcript_outlooks` before the next screener run
  and recut `STANCE_BANDS` at the same shares: the ranking compares each call
  with the run's median, and calls scored under two sets of weights are not
  comparable. No model is asked anything.
- **NSE shareholding and bulk/block deals are display evidence, read from the
  exchange.** `workers/shareholding.py` (a step of the Quarterly filings
  workflow) stores each quarter's shareholding pattern, parsed once from its
  XBRL by `screener/shareholding.py`, in `shareholding_patterns`, and the
  exchange's deal history in `bulk_block_deals`; the stock page's Shareholding
  tab (NSE only) reads both. FII and DII are the filing's own "Institutions
  (Foreign/Domestic)" subtotals and public is the rest, as StockScans and
  Screener print it; a group nobody is in is 0, since a complete filing omits
  its subtotal. Filings before September 2022 have no such split, so the
  sweep starts there. The deals export's JSON stops at 70 rows; its CSV form
  (`csv=true`) is complete. The tables are in `storage/shareholding_schema.sql`
  and must be applied by hand.
- **The US Results page reads the same `quarterly_filings` table, filled from the
  statements.** `workers/us_results.py` (a step of the US Financial statements
  workflow) writes each stock's last five vendor quarters as `market = 'US'` rows,
  so `quarterly_result_feed` and the page need no US branch. A US row has the
  company's fiscal `period_end`, one basis, no document link, and `broadcast_at` =
  when we first saw the quarter (the bell's `market_events` time), not the
  company's release; a stored quarter is not rewritten. Every reader of the table
  filters on `market` (`DashboardRepository._scoped`): a US ticker can equal an
  NSE symbol.
- **Upcoming results dates and earnings calls are one row per stock.**
  `workers/upcoming_events.py` (a step of the Quarterly filings workflow, NSE
  only) writes `upcoming_events`: `next_result_date` from the board-meeting
  feed (the later intimation wins a reschedule), and `next_call_at` /
  `next_call_date` from the "Con. Call" notice's PDF -- the API carries
  neither. A call is an *earnings* call, not an investor meet, when the
  notice's text names a conference or earnings call and ties it to results;
  a time is kept only in India time. The worker clears a passed date, reads
  a notice once (`updated_at` is when it last looked at the stock), and
  skips BSE-only names. Display evidence; the table is in
  `storage/upcoming_events_schema.sql`, applied by hand.
- **US upcoming results come from Alpha Vantage's earnings calendar.**
  `workers/us_upcoming.py` (a step of the US Financial statements workflow, the
  first run of the day, before 09:00 UTC) makes one request a day, keyed by the `ALPHAVANTAGE_API_KEY`
  secret, and writes `next_result_date` and a before/after-market note to
  `upcoming_events` for universe stocks (`market = 'US'`; NSE rows untouched). No
  estimates are kept. A missing key, a refusal or a calendar under 1,000 rows (it holds ~3,500) warns,
  writes nothing and keeps the step green.
  Alpha Vantage free key: personal, non-commercial use only (ToS s.2a); if the
  dashboard gains other viewers, this source must be dropped or licensed.
- **Live prices are display-only, every five minutes during the session.**
  `workers/live_quotes.py` (the Live quotes workflow, dispatch-only:
  cron-job.org calls it every 5 minutes on weekdays; do not add a
  `schedule:`) writes `live_quotes`, one row per market and symbol from
  Yahoo's batch quote endpoint, and once a day the constituents of each
  `MarketProfile.live_indices` into `index_members`. The dashboard reads them
  in the browser after render: the grid's Price and 1D, the stock page's
  tiles, the Market page's movers by index (`live_market()`), and each index's
  page (`/[market]/indices/[slug]`), whose constituents table is
  `index_members` read through the screener's own `getSnapshotPage`. Nothing
  scores or sorts on them, and only that page filters, by membership alone; a
  quote shows only when it is from a later
  session than the row's bar. A change past `max_open_gap` is withheld as a
  unit change, not a move. The tables are in
  `storage/live_quotes_schema.sql` and must be applied by hand. The Market
  page's breadth charts take a live point from the same quotes:
  `tools/publish_market_breadth.py` also writes each stock's next-session
  levels (`market_breadth_levels`: yesterday's EMAs -- a price is above
  today's EMA exactly when it is above yesterday's -- the prior year's high
  and low, the six-month base), and `live_breadth()` counts the live prices
  against them, so the live point equals the close the evening run will
  publish at that price. Stage 2 and RS rating stay on the last close. Both
  are in `storage/market_breadth_schema.sql`, applied by hand.
- **A price ratio is the price over a stored basis, worked out where the
  price is.** `valuation_basis` holds each symbol's company side -- trailing
  profit, book equity, trailing EBITDA, debt, cash, shares, dividend -- as
  totals (`screener/valuation_basis.py`). The trailing year is the latest
  four filed quarters on one basis where NSE filings have them
  (`trailing_year`), else Yahoo's; the vendor's quarter is kept as the
  basis's `period_end` so a filed year never replaces a later one. Two
  writers: the dashboard publisher, every symbol of the evening run; and
  `workers/quarterly_filings.refresh_valuation_basis`, the trailing lines
  alone, minutes after a company files. Scoring works the ratios out at the
  close (`price_ratios`); the dashboard reads them at the live quote from the
  `live_valuation` view (grid, stock page, results card, through
  `LiveRatio`). The view's arithmetic is held equal to `price_ratios` by
  `tests/test_valuation_basis.py`, which runs the view's SQL on SQLite. Both
  are in `storage/valuation_basis_schema.sql`, applied by hand; apply it
  before deploying the dashboard, whose stock quotes are read through the view.
- **NSE-only evidence degrades, it does not fail.** The impact-cost overlay
  (`screener/liquidity.py`), transcript sentiment and the VIGIL red-flag feed
  have no US counterpart. They are switched off by env in the US workflow and
  the affected columns read "Unavailable" or stay neutral — never zero.

## Boundaries that matter

- **`screener/recommendation.py` is the only writer of canonical decisions**
  (`Rating`, `Rank`, `Buy_Eligible`, `Final_Score`, ...). The scoring layer emits
  components and `Core_*` diagnostics only. A rescored export purges stale
  canonical columns first.
- **A snapshot row's payload is a Storage object, not a column.** The complete
  source record is `market-data/snapshot-payload/{MARKET}/{run_date}/{symbol}.json.gz`,
  written before the run is published and swept with the run when it is
  pruned; `getStock` reads it. In the column it was a third of the free
  database for a single day (Oct 2026).
- **`backtest/` is point-in-time.** It must never read anything the model could
  not have seen on the day being simulated.
- **`app.py` is also a backwards-compatible API.** It re-exports names that
  callers and tests import directly, so its "unused" imports are deliberate —
  `pyproject.toml` exempts it from `F401`. Do not strip them.
- **Dependencies are locked.** Edit `requirements*.in`, then regenerate the
  `.txt` locks (each lock header carries its command). `torch` and `transformers`
  stay in the production lock because `validation/reproducibility.py` records
  their versions in the run manifest; removing them changes the manifest hash.

## Layout

```
screener/     live scoring path (scoring/ is a package: constants, points,
              fundamental, sector_models, technical, engine); markets.py and
              universe.py hold the per-market facts and universe sources
backtest/     point-in-time simulation, deliberately separate from the live path
workers/      scheduled jobs (dashboard publish, transcripts, call recordings,
              red flags)
storage/      Supabase repositories
validation/   reproducibility manifests and replay
dashboard/    Next.js front end, with its own README; routes are nested
              under /[market] (/ind, /us; /nse redirects). Concalls, Results and Returns
              share the header's Tools tab (`lib/tools.ts`, the `(tools)` route group);
              Market is a tab of its own
```

## Gotchas

- The repo is edited from both Windows and WSL. `.gitattributes` pins LF; keep
  `core.autocrlf=input` locally or the whole tree shows as modified.
- **The scheduled workflows run the suite inside their own job env.** Every
  variable in a workflow's `env:` block leaks into its `unittest` pre-flight, so
  a test that assumes a variable is unset passes in CI and fails the cron run
  (US, 29 Sept 2026: `PRICE_BAR_PROBE_ENABLED`). Test defaults through
  `config_with_env_cleared(...)` in `tests/test_markets.py`. CI's
  `workflow-env-tests` job replays each workflow's test step; reproduce one
  locally with `python -m tools.run_tests_under_workflow_env <workflow.yml>`.
- **The backtest archive under `reports_advanced/` is local and not in git.**
  NSE's results endpoint thins out after early 2025, so
  `reports_advanced/backtest` ends at FY2024 annual and December 2024 quarterly
  filings. `python -m tools.extend_fundamental_panel` writes
  `reports_advanced/backtest_ext`, the same archive with later periods taken
  from the stored vendor statements; pass that as `--root` for any backtest
  that runs past mid-2025, and to `tools.backfill_returns_history build`.
- `ruff`'s ratchet list in `pyproject.toml` records rules the codebase does not
  yet satisfy, with counts. Removing an entry means fixing its violations.
