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
  Store in the US. Any new query against `screener_snapshot`, `screener_history`
  or `price_series` must filter on it; `DashboardRepository` is scoped to one
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
- **NSE latest-quarter growth comes from the exchange's results filings; Yahoo
  is the fallback.** Yahoo republishes a result days or weeks after it is
  filed, so through a results season `Revenue_Growth` and `Earnings_Growth`
  described the quarter before. `QUARTERLY_RESULTS_FILINGS_ENABLED` (set in the
  NSE workflow) makes `screener/quarterly_results.py` read NSE's
  integrated-filing index and measure both from the filed documents, by the
  backtest's own rule (`backtest.fundamentals.QuarterPanel`: both quarters on
  one basis, profit not EPS, no rate on a non-positive base). Yahoo's figures
  stand for banks and insurers (a different statement), a company with no
  year-ago filing, and one where Yahoo is already on a later quarter; see
  `quarter_results_*` in the run diagnostics. `workers/financial_statements.py`
  adds a filed quarter Yahoo lacks to the Financials tab on the same index,
  only where the filing reproduces Yahoo's revenue on a quarter both have.
  Measure the two sources with `python -m tools.compare_quarter_growth_sources`.
  The index begins in April 2025; the older endpoint `backtest/filings.py`
  reads ends that January. Statements, valuation ratios and prices are still
  Yahoo's.
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
  `workers/market_events.py` (a step in the Financial statements workflow)
  writes `market_events`, one row per `(market, kind, symbol, event_key)`,
  written once: a `results` event from NSE's filing index, or in the US from
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
- **Management's stance is read by the outlook step and never scored.** The
  outlook request also asks where the company's prospects stand after the
  call (`stance`: bullish to bearish, with the sentence behind it). The
  question is a weighing of what management stated against the difficulty it
  conceded, which the model must quote first (`stance.concern`): asked for
  management's own view, it called 29 of 33 calls "optimistic", a bank
  lowering its guidance among them (14 Oct 2026). It is display
  evidence for the Concalls page and deliberately outside `verified_fields`,
  which is how the screener knows a call stated something scorable. Do not
  label a call from the word-list tone score: its risk component counts
  vocabulary, and called a wealth manager "Bearish" for discussing market
  risk. `OUTLOOK_VERSION` was not bumped, so calls read earlier have no
  stance until `tools.extract_transcript_outlook --refresh-since` reads them
  again -- which can also move their outlook scores, unless it is run with
  `--stance-only`, which keeps every scored item as first read.
- **NSE-only evidence degrades, it does not fail.** The impact-cost overlay
  (`screener/liquidity.py`), transcript sentiment and the VIGIL red-flag feed
  have no US counterpart. They are switched off by env in the US workflow and
  the affected columns read "Unavailable" or stay neutral — never zero.

## Boundaries that matter

- **`screener/recommendation.py` is the only writer of canonical decisions**
  (`Rating`, `Rank`, `Buy_Eligible`, `Final_Score`, ...). The scoring layer emits
  components and `Core_*` diagnostics only. A rescored export purges stale
  canonical columns first.
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
              under /[market] (/nse, /us). Market and Concalls share the
              header's Tools tab (`lib/tools.ts`, the `(tools)` route group)
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
