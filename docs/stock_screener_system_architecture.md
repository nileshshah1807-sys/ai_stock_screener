# AI Stock Screener — As-Built System Architecture Design

- **Status:** implementation-derived design document
- **Scope:** the `app.run_daily_analysis()` production path, for both markets (NSE and US), and the scheduled jobs around it
- **Scheduled production contract:** model `5.2.0` / recommendation policy `5.5.0` / output schema `4.2.0`, in both markets
- **Local and manual-daily default:** `4.0.0-candidate`, with the factor switch off
- **Last reviewed against code:** 2026-10-25 (`origin/main` at `91a5e3a`)
- **Live workflows:** `daily-stock-screener.yml` (NSE), `daily-us-screener.yml`, `financial-statements.yml`, `quarterly-filings.yml`, `live-quotes.yml`, `price-series.yml`, `market-breadth.yml`, `transcript-sentiment.yml`, `call-recordings.yml`, `red-flag-shadow.yml` and `ci.yml` (section 15.5 says what each does; branching rules are in `development_guidelines.md`)

> **Two models live in this codebase.** Sections 1-19 describe the shared pipeline and
> the legacy **4.x model**, which remains the local/runtime default (`FACTOR_MODEL_ENABLED=False`)
> and the isolated validation path. Section 20 describes the **Model 5.x factor
> architecture** that scheduled production runs: five separable factor blocks, MA200 trend gates,
> a market-regime overlay and a run-percentile score. A scheduled run, or a dispatch with
> `mode=production`, selects it explicitly in GitHub Actions. Where Model 5 changes a rule in
> sections 1-19, the text says so, and section 20 holds the details.

> **Research-model boundary.** This application produces deterministic research ranks and heuristic rating labels. `Rating`, `Decision_Score`, and `Final_Score` are not forecasts of return, fair value, or probability of profit. The exported `Model_Validation_Status` says what has been tested and what has not: section 20.9 gives the evidence and its limits. The system's purpose is to make the screening logic auditable, reproducible, and reviewable.

## 1. Executive summary

The application is an equity research screener for two markets, India (NSE, plus companies listed on BSE alone) and the US. `MARKET` selects the market and everything else follows from it (section 2). A run creates one row per successfully collected market-data symbol, derives a research score from fundamentals and price history, adds independent DCF and earnings-call evidence, then applies hard policy gates that cap or label the rating. The published score (`Evidence_Score`) is a percentile of the whole evidence across that run, so a rating such as STRONG BUY means "top 30% of today's universe" and the gates are the absolute checks. The primary rank orders by that score, then the research score, then fewer gate failures, then ticker symbol (section 12).

The main design principles implemented in the code are:

1. **Research universe first, execution overlay later.** The default full-NSE run retains the broad successfully collected universe; liquidity normally affects `Actionable_Rank`, not `Final_Score` or primary `Rank`. (Under Model 5 an illiquid name cannot be rated BUY: section 20.5.)
2. **Completed-bar consistency.** Each price-sensitive technical feature uses the same completed daily bar of the market. Raw `Current_Price` is retained for traded-value/valuation display; adjusted `Technical_Price` is used for returns, indicators, and chart gates.
3. **Score/evidence/policy separation.** Scoring, DCF, transcripts, liquidity, and red flags are evidence producers. Only `RecommendationPolicy` publishes canonical score, rating, eligibility, gate, and rank fields.
4. **Fail-closed high conviction.** Missing coverage, stale fundamentals, invalid specialist-model evidence, multiple data anomalies, and weak trend structure cap a candidate below BUY or STRONG BUY even if its raw score is high.
5. **Deterministic audit trail.** Stable sort order, decimal half-up rounding, collection diagnostics, output manifests, configuration hashing, and per-symbol gate reasons are exported.
6. **Immutable completed-session publication.** Scheduled work is keyed to the expected completed trading session of its market, not the calendar day. An already-published session is reused on weekends, holidays, and recovery cron attempts instead of being rescored against revised vendor metadata.
7. **Wide write model, narrow read model.** The CSV remains the complete research contract. Supabase stores indexed dashboard fields plus the entire source row in `payload`, while the authenticated Next.js application reads only the projections each surface needs.

## 2. Architecture overview

**One pipeline, two markets.** `MARKET` (`NSE` by default, or `US`) picks a `MarketProfile` in `screener/markets.py`: ticker suffix, timezone, session cutoff, benchmark index, universe source, currency and live indices. A profile supplies defaults only; every environment variable keeps its name and precedence, so an unset `MARKET` gives exactly the NSE behaviour. The scoring layer (`screener/scoring/`, `factors.py`, `stage.py`) ranks within one run's frame and has no market branch. Environment variables named `*_INR` and `*_IST` are read as the market's currency and local time (`MIN_AVG_TURNOVER_INR` is dollars on a US run; the bar cutoff is 16:15 IST for NSE and 16:00 ET for the US). `market` is part of every stored key, because a symbol does not identify a company across exchanges.

```text
                                  External sources
          ┌──────────────────────────────────────────────────────────────┐
          │ NSE list + BSE-only companies / US list; NSE liquidity files │
          │ Yahoo prices (4.x 6mo/v6; Model 5 2y/v7); SEC EDGAR (US)     │
          │ Supabase: filings, transcripts, red flags, dashboard data    │
          │ Brandfetch CDN: browser-rendered issuer logos by domain      │
          │ Google News RSS: display-only headline sentiment             │
          └──────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│ 1. Collection and normalization                                                     │
│    StockDataCollector -> completed price-bar selection -> technical features       │
│    NSELiquidityProvider -> optional emergency prefilter -> fundamentals -> merge   │
│    align_valuation_to_completed_price_bar                                           │
└───────────────────────────────────────────────────────────────────────────────────┘
                                       │ DataFrame: one row / research symbol
                                       ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│ 2. Core scoring (`StockScorer`)                                                     │
│ 4.x: generic or specialist fundamentals + technicals (0-100 each)                  │
│ 4.x core = 0.70 * Fundamental + 0.30 * Technical; Model 5: FactorModel             │
│    exports coverage, anomalies, component points, provisional core diagnostics     │
└───────────────────────────────────────────────────────────────────────────────────┘
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
┌──────────────────────────────────────┐  ┌───────────────────────────────────────┐
│ 3a. Reverse DCF evidence             │  │ 3b. Transcript evidence                │
│ Base-case value / market-cap -> score │  │ Current-cycle cached call only         │
│ reported positive FCF only for blend  │  │ age weighting; two-sided; outlook-led  │
└──────────────────────────────────────┘  └───────────────────────────────────────┘
                    └──────────────────┬──────────────────┘
                                       ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│ 4. Authoritative recommendation policy (`RecommendationPolicy.finalize`)            │
│    blend evidence -> enumerate gate failures -> score ceiling -> rating -> ranks    │
└───────────────────────────────────────────────────────────────────────────────────┘
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
┌──────────────────────────────────────┐  ┌───────────────────────────────────────┐
│ 5a. Liquidity actionability           │  │ 5b. Optional red-flag shadow evidence │
│ NSE Group I / impact cost or turnover │  │ cached VIGIL-style evidence, no live   │
│ changes Actionable_Rank only          │  │ score or rating mutation               │
└──────────────────────────────────────┘  └───────────────────────────────────────┘
                    └──────────────────┬──────────────────┘
                                       ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│ 6. Publish and monitor                                                              │
│ CSV + dashboard + optional email/PDF/WhatsApp + manifest + diagnostics + backtest  │
└───────────────────────────────────────────────────────────────────────────────────┘
```

## 3. Component map and responsibilities

| Layer | Main implementation | Responsibility | Can change canonical `Rating` / `Final_Score`? |
|---|---|---|---|
| Composition root | `app.py::run_daily_analysis` | Orders the daily job, handles output/reporting, assigns run provenance. `app.py` also re-exports names that callers and tests import, so its apparently unused imports are deliberate. | Indirectly, by calling finalizer once. |
| Runtime configuration | `screener/runtime.py::Config` | Environment-backed defaults; optionally overridden by `config_local.py`. | Policy parameters only. |
| Market profiles | `screener/markets.py::MarketProfile` | One profile per market: suffix, timezone, session cutoff, benchmark, universe source, currency, live indices. `is_bse_only` tells a `.BO` symbol apart. | No. |
| Universe | `screener/universe.py` | Builds the symbol list for the market's source (NSE, NSE plus BSE-only, S&P 500, S&P 1500, all US listings). | No. |
| Collection | `screener/data_collection.py::StockDataCollector` | Universe, model-specific Yahoo OHLCV (4.x `6mo`/v6; Model 5 `2y`/v7), cache reuse, Yahoo fundamentals, collection diagnostics. | No. |
| Price bar repair | `screener/session_bars.py`, `screener/price_basis.py` | Fills one missing session bar from NSE's bhavcopy; restates price history across demergers, rights issues and part-adjusted splits and drops single-session bad prints. | No. |
| Technical calculation | `screener/market_data.py::TechnicalEnhancer` | RSI, ADX/+DI/-DI, StochRSI, ATR, returns. | No. |
| Liquidity source | `screener/liquidity.py::NSELiquidityProvider` | Joins NSE monthly Group I/II/III and Rs1 lakh mean impact cost (NSE only). | No. |
| Annual statements | `screener/statements.py::FinancialStatementCollector`, `screener/edgar.py` | Caches annual statements (SEC EDGAR first in the US, Yahoo otherwise), derives factor inputs, and safely fills missing quote metadata with source markers. | No. |
| Quarterly results | `screener/quarterly_results.py::QuarterlyResultsCollector` | NSE: reads the stored results filings for the latest-quarter growth figures and the trailing-year line items. | No. |
| Valuation basis | `screener/valuation_basis.py` | The company side of each price ratio, stored per symbol; `price_ratios` divides price by it. | No. |
| Legacy core model | `screener/scoring/` (`engine.py::StockScorer`, `fundamental.py`, `technical.py`, `sector_models.py`, `points.py`, `constants.py`) | Fundamental/technical component scores, sector-relative comparison, coverage, specialist quality checks. Also supplies the coverage, anomaly and specialist-routing evidence the policy needs under Model 5. | Exports only provisional `Core_*` diagnostics. |
| Factor model | `screener/factors.py::FactorModel`, `screener/benchmark.py`, `screener/stage.py` | Model 5 research score, regime, stage and relative-strength rating (display only). | No; emits `Research_Score` and block scores. |
| Valuation evidence | `screener/valuation.py::ReverseDCFModel` | Reverse-DCF diagnostics and a valuation score. | No. |
| Transcript evidence | `scoring/transcript_enricher.py::TranscriptSentimentEnricher` | Loads cached tone and outlook records and establishes recency/cycle eligibility. | No. |
| Decision policy | `screener/recommendation.py::RecommendationPolicy` | Evidence blend, policy gates, ceilings, ratings, stability diagnostics, primary ranks. | **Yes; sole authority.** |
| Execution overlay | `LiquidityQualityEnricher` and `rank_actionable_recommendations` | Position-size actionability and `Actionable_Rank`. | No. |
| Risk shadow layer | `red_flags/enricher.py`, `red_flags/shadow.py` | Cached red flags and counterfactual outcomes if confirmed. | No. |
| Outputs | `screener/reporting.py`, `validation/reproducibility.py` | Dashboard/report delivery, CSV, provenance manifest and hashes. | No. |
| Schedule guard | `workers/scheduled_session_guard.py` | Compares the expected completed session with the latest completed Supabase run before expensive scheduled work. | No. |
| Dashboard publisher | `workers/dashboard_publisher.py`, `storage/dashboard_repository.py` | Maps the CSV into run, snapshot, and slim-history tables using a reserve/write/complete protocol. | No; publishes existing decisions. |
| Feature workers | `workers/` (`quarterly_filings`, `shareholding`, `market_events`, `live_quotes`, `new_listings`, `call_recordings`, ...) | Fill display tables the dashboard reads. Nothing in the score reads them, except the filings table that feeds growth (above). | No. |
| Web read model | `dashboard/` | Authenticated Next.js application, one tree per market (section 15.5). | No; read-only for research data. |

## 4. End-to-end run sequence

`app.run_daily_analysis()` executes the following order. This order matters because later evidence is allowed to modify the evidence score but not bypass gates.

1. Instantiate `Config` (which resolves the `MarketProfile`), determine `analysis_now` in the market's timezone (`Asia/Kolkata` by default), and initialize cache folders.
2. Build the universe through `StockDataCollector.get_comprehensive_stock_list()` (section 5.1).
3. Download/reuse the model-specific OHLCV window (`6mo` for the default 4.x path, `2y` for Model 5); repair the price basis; retain only symbols with a valid completed and aligned daily bar and enough usable history (section 5.2).
4. Join NSE liquidity categories and impact-cost evidence once for the collected symbols (NSE only).
5. Apply the liquidity prefilter only when all of these are true: `LIQUIDITY_FILTER_ENABLED`, `SCAN_ALL_NSE`, and `PREFILTER_RESEARCH_UNIVERSE_BY_LIQUIDITY`. It is off in the NSE run and on in the US run (section 13.3).
6. Fetch or reuse fundamentals and left-join them to the technical universe. A fundamental miss does not delete a technically collected symbol; it becomes missing/limited evidence and is later prevented from receiving BUY conviction.
7. On NSE, `QuarterlyResultsCollector.enrich` replaces the vendor's latest-quarter growth and trailing-year figures with figures measured from stored results filings, where a company has them (section 5.4).
8. Recalculate price-dependent valuation ratios using the same completed close used for price technicals.
9. When Model 5 is enabled, fetch/reuse annual statements, fill only absent quote fields from statement-derived equivalents, record a per-field source, and rerun completed-close valuation alignment. Enforce the run-wide statement-coverage floor before scoring.
10. Run `StockScorer.score_all_stocks()` to create the 4.x core diagnostics, including exact missing fundamental and technical fields.
11. If enabled, run `ReverseDCFModel.enrich()`.
12. If enabled, load precomputed transcript evidence (NSE; transcripts are off in the US run). A transcript failure is fatal by default (`TRANSCRIPT_FAIL_ON_ERROR=True`), but can be configured to log and skip.
13. When Model 5 is selected, load benchmark context and run the factor model to create its block scores, applicability-aware coverage, per-input Value audit, and research score.
14. Attach liquidity/actionability evidence before policy finalization so Model 5 can enforce its BUY liquidity gate without letting execution capacity prefilter the research universe.
15. Run `finalize_recommendations()`: the sole writer of canonical decision fields and primary research ranks.
16. Optionally attach red-flag records and generate a shadow-only counterfactual, then generate `Actionable_Rank` without changing the primary investment ordering.
17. Attach the display-only expectations gap (forward P/E, market-implied growth, guidance transition) and the valuation basis. Neither can change a score, gate or rank.
18. Add model/config/run provenance, fetch display-only news sentiment for the already-ranked top N rows, write CSV/manifest/diagnostics/dashboard, and optionally send reports.
19. Optionally append the result to a model-version-separated monitoring log (section 15.3).

The scheduled GitHub workflow wraps this in an outer publication protocol:

1. The workflow runs in several slots a day because GitHub starts scheduled jobs late and sometimes drops one (NSE: four slots from 11:07 UTC; US: 21:37 and 23:37 UTC plus retries at 01:37, 03:37 and 05:37 UTC). A same-UTC-day success check and the session guard suppress the later slots.
2. `scheduled_session_guard` suppresses weekend, configured-holiday, and already-published completed-session rebuilds even when no workflow succeeded on the current calendar day.
3. The report artifact and both cache namespaces are saved before dashboard publication.
4. `dashboard_publisher --if-exists skip` treats a race or replay of an already-published trading date as a successful no-op (section 15.5 explains the consequence).
5. Only a scheduled run, or a dispatch with `mode=production`, updates the Supabase read model; a dispatch with `mode=validation` publishes nothing.

## 5. Research universe, data contracts, and collection controls

### 5.1 Universe selection

The market's profile names its universe source (`NSE_UNIVERSE_SOURCE` or `US_UNIVERSE_SOURCE`, `screener/universe.py`).

- **NSE.** The collector retrieves NSE's `EQUITY_L.csv`. Production sets `nse_with_bse_only`, which adds every BSE mainboard company whose ISIN NSE does not list, read from the last five BSE bhavcopies (BSE's daily price files). Such a company is screened as `SYMBOL.BO`, its Yahoo ticker, so it can never equal an NSE symbol; a company listed on both exchanges is screened once, as NSE. If no bhavcopy can be found the run proceeds with NSE only and records `ok:partial` with the note `bse:unavailable`.
- **US.** `sp500`, `sp1500` or `all_listed`; production uses `all_listed`.
- **Safety net.** A small fixed list of liquid names (`MarketProfile.safety_net_symbols`) is added to the list, and kept if the master file fails. Symbols longer than 20 characters are dropped.
- **Custom watchlist.** In watchlist mode (`SCAN_ALL_NSE=False`), `CUSTOM_WATCHLIST` replaces the whole universe.
- **Young listings are not scored.** A symbol needs at least 60 sessions of price history (`MIN_PRICE_SESSIONS_REQUIRED`) and must pass the turnover floor. Those that do not are published separately as `new_listings` (section 13.4) and have no rank.
- Collection diagnostics persist the selected, requested, collected, failed, and missing symbols. This prevents a different network-collected cross-section from appearing reproducible merely because code/config were unchanged.

### 5.2 Completed market-bar policy

The history contract is selected with the model. With `FACTOR_MODEL_ENABLED=false`, the
default 4.x path retains its established `6mo` download and technical-cache contract v6.
Enabling Model 5 selects `2y` and technical-cache contract v7 because its 200-day average,
12-1 momentum formation window and one-year drawdown cannot be expressed in six months.
The distinct cache versions prevent either model from accepting incompatible technical rows.

The longer Model 5 window does **not** redefine features that are *defined* on a six-month
basis. `Avg_Turnover_INR`, `Pct_Change_6M`, `High_6M` and `Low_6M` are pinned to
`LEGACY_HISTORY_WINDOW_SESSIONS` (126) so a liquidity floor or a "6M" return stays comparable
with previously published runs. One related defect was fixed in the same change:
`Pct_Change_6M` previously spanned *the whole downloaded history*, so a stock with only 70
sessions of history had its 70-session return published as a six-month return. It is now an
explicit 126-session lookback and is missing when that history does not exist.

Daily data is collected from Yahoo Finance with `auto_adjust=False`; the collector uses both raw and adjusted series deliberately:

| Purpose | Price scale | Column / use |
|---|---|---|
| Trading value, liquidity turnover, valuation/display close | raw daily close | `Current_Price` |
| Returns, moving averages, RSI, MACD, ADX, ATR, Bollinger position, chart gates | split/dividend-adjusted OHLC | `Technical_Price` and technical columns |

A fresh bar is aligned only if it is the latest expected completed NSE session. A separately
labelled prior-cache fallback may remain solely when a per-symbol provider request fails:

- Default time zone: `Asia/Kolkata` (NSE) or `America/New_York` (US).
- Daily session completion cutoff: `16:15` IST for NSE, `16:00` ET for the US (`MARKET_BAR_COMPLETE_AFTER_IST`).
- Before the cutoff, today's bar is excluded unless the explicit `ALLOW_PROVISIONAL_MARKET_BARS` escape hatch is enabled.
- After the cutoff, a normal NSE session needs today's complete bar; weekends and configured NSE holidays use the prior expected session.
- A fresh provider row is admitted only when its provenance is valid. If the provider fails for one symbol, a schema-valid prior cached row may be retained as `stale_cached_fallback`; it carries its real session lag, is never described as current, and cannot support BUY conviction.
- **NSE bhavcopy fallback.** When Yahoo lacks the expected session's bar for a symbol, `screener/session_bars.py` takes that one bar from NSE's daily file (`PRICE_BAR_FALLBACK_ENABLED`, set in the NSE workflow). It fills only that bar, and only when the bar continues Yahoo's history. The patched symbols are listed in the run diagnostics as `technical_session_bar_patched_symbols`. There is no US counterpart, so a Yahoo gap there still fails the alignment guard.
- A symbol with neither fresh evidence nor a usable prior row is unresolved and excluded. Diagnostics distinguish provider failures, stale fallbacks, and unresolved symbols instead of reporting all three as one failure class.
- Completed daily bars are immutable. Cache validity is therefore keyed primarily to the recorded expected exchange session, schema, indicator version, completion state, and provenance rather than expiring a Friday snapshot merely because wall-clock hours passed over a weekend.

**Change of price basis.** Neither NSE's corporate-action feed nor Yahoo's adjustment can be used as served: a demerger or rights issue leaves a cliff of 30-90% that no holder took, and some splits are back-adjusted only part of the way. With `PRICE_BASIS_RESTATEMENT_ENABLED` (NSE workflow), `screener/price_basis.py` restates Yahoo's adjusted close from the security's own bars and drops single-session bad prints. Two rules in `backtest/corporate_actions.py` size a change: `ex_date_price_factor` (previous close over the ex-date open, for an action the feed names) and `open_gap_factor` (an open beyond `MarketProfile.max_open_gap` was not traded to; NSE caps its opening auction at 20%, the US does not, so the rule is off there). The restated symbols appear in the diagnostics as `technical_price_basis_restated_symbols` and `technical_bad_print_symbols`. This is display-grade: the backtest still excludes a position that spans a demerger, rights issue or buyback.

The system exports `Price_Bar_As_Of`, `Expected_Price_Bar_As_Of`, `Price_Bar_Session_Lag`, `Price_Bar_Aligned`, `Price_Bar_Complete`, `Price_Session_Status`, `Analysis_As_Of`, and `Price_Fetched_At`.

### 5.3 Price-aligned valuation inputs

Yahoo quote metadata and a daily close can have different observation times. Immediately after merging, `align_valuation_to_completed_price_bar()` preserves fetched values in `*_As_Fetched` audit columns and, where possible, recomputes:

```text
PE_Ratio       = Current_Price / EPS
PB_Ratio       = Current_Price / Book_Value
Market_Cap     = Current_Price * Shares_Outstanding
EnterpriseValue = Market_Cap + Total_Debt - Total_Cash
EV_EBITDA      = EnterpriseValue / EBITDA
Dividend_Yield_Ratio = annual dividend per share / Current_Price
Dividend_Yield = 100 * Dividend_Yield_Ratio
```

The arithmetic is owned by `screener/valuation_basis.py::price_ratios`. A **valuation basis** is each symbol's company side of every ratio (trailing profit, book equity, trailing EBITDA, debt, cash, shares, dividend) stored as totals. The trailing year is the latest four filed quarters on one basis where NSE filings have them, else Yahoo's. The screener divides the close by the basis; the dashboard divides the live quote by the same stored basis (the `live_valuation` view), and `tests/test_valuation_basis.py` holds the two equal. The basis is written by the dashboard publisher for every symbol of the evening run, and by the Quarterly filings worker minutes after a company files.

A ratio is recomputed only if all needed denominators are valid (and nonzero where required); otherwise the fetched value remains for audit. `*_Price_Aligned` flags and `Valuation_Price_Alignment_Status` report whether the metric was aligned.

### 5.4 Fundamental collection and failure behavior

Fundamentals come from Yahoo quote metadata and use a seven-day cache by default. On NSE, `screener/quarterly_results.py::QuarterlyResultsCollector` (enabled by `QUARTERLY_RESULTS_FILINGS_ENABLED`, read only where the run has Supabase credentials) then replaces, where a company's results filings support it, the latest-quarter `Revenue_Growth` and `Earnings_Growth` and the trailing-year EPS, EBITDA, margins and ROE with figures measured from the filings. The filings are read from the `quarterly_filings` table, which the Quarterly filings workflow fills every 15 minutes as companies file; the daily run fetches nothing from the exchange. The rule matches the backtest's (`backtest.fundamentals.QuarterPanel`): both quarters on one basis (consolidated preferred), profit not EPS, no rate on a non-positive base. Banks and insurers file a different statement; their filings are stored for display, but the screener keeps Yahoo's growth for them (`DISPLAY_ONLY_TAXONOMIES`), as it does for a company with no year-ago filing. In the US, and for any symbol without a filing, Yahoo's figures stand. The rest of the record is unchanged. The collector requires a cache schema containing company metadata, raw valuation denominators, sector/industry, and provenance. It fetches at a throttled rate and retains stale cached rows on a transient request failure. A fundamental record is left-joined to technical rows:

```text
research universe = successfully collected technical symbols
merged frame      = technical frame LEFT JOIN fundamental frame on Symbol
```

Therefore, a fundamental failure does not shrink the ranked universe silently. Instead, `Fundamental_Record_Available=False`, missing fields decrease coverage, and the final policy caps high-conviction labels.

### 5.4.1 Statement-derived recovery and field provenance

In the US, `STATEMENT_SOURCE=edgar` makes the collector ask SEC EDGAR (`screener/edgar.py`) first and Yahoo only for what EDGAR cannot serve (filers reporting in another currency, a ticker SEC does not list). EDGAR's facts are rebuilt into Yahoo-shaped frames, so `derive_statement_factors` is shared and the scoring layer has no market branch. SEC rejects clients that name no contact: the address lives in the `SEC_USER_AGENT` repository variable, and without it the run warns and uses Yahoo throughout. Prices and quote metadata are still Yahoo's.

Model 5 already downloads annual income, balance-sheet, and cash-flow statements (EDGAR or Yahoo) for its factor blocks. Quote metadata is convenient but sparse for many NSE issuers, so `apply_statement_fallbacks()` reuses that same issuer evidence for a deliberately small set of equivalent raw fields:

| Quote field filled only when absent | Annual-statement source |
|---|---|
| `ROA` | net income divided by average total assets |
| `Current_Ratio` | current assets divided by current liabilities |
| `Debt_to_Equity` | total debt divided by equity, exported in Yahoo-compatible percentage points |
| `Free_CashFlow` | reported FCF, or operating cash flow plus the normally negative capital-expenditure line |
| `Total_Debt`, `Total_Cash`, `Shares_Outstanding` | latest annual balance sheet |
| `Total_Revenue`, `EBITDA` | latest annual income statement |

A non-null quote value always wins; the fallback does not blend competing definitions or overwrite provider data. Every target exports `<Field>_Source`, and FCF distinguishes a reported value from the OCF-plus-capex derivation. Statement schema version 2 invalidates the older cache once so the added raw fields are rebuilt consistently.

After these fallbacks, `align_valuation_to_completed_price_bar()` runs a second time. This allows statement-derived shares, debt, cash, and EBITDA to complete an aligned market cap and EV/EBITDA while retaining the originally fetched valuation in its audit columns. The scorer then computes fundamental coverage from the recovered row and exports `Fundamental_Missing_Fields` and `Technical_Missing_Components` for anything still unavailable.

### 5.5 Liquidity input calculations

For raw close `C_t` and volume `V_t`, daily turnover is `T_t = C_t * V_t`. Rows with `Close <= 0` or `Volume < 0` are dropped first. The collector exports:

```text
Avg_Turnover_INR         = mean(T_t over the trailing LEGACY_HISTORY_WINDOW_SESSIONS = 126 sessions)
Median_Turnover_20D_INR  = median(T_t over trailing 20 sessions)
Turnover_P10_20D_INR     = 10th percentile(T_t over trailing 20 sessions)
Median_Turnover_60D_INR  = median(T_t over trailing 60 sessions)
Turnover_Top5_Share_60D  = sum(largest five T_t in trailing 60) / sum(T_t in trailing 60)   # 1.0 when the 60-day turnover is 0
Trading_Frequency_60D    = count(V_t > 0 in trailing 60) / observed trailing-60 sessions
```

Zero-volume sessions are retained so intermittent trading cannot look artificially liquid. The `_INR` suffix is a name kept for compatibility; the values are in the market's currency.

The collection-stage price-volume confirmation uses a standard 21-session Chaikin Money Flow calculation on adjusted prices:

```text
MFM_t  = (2 * Close_t - High_t - Low_t) / (High_t - Low_t)    # zero range -> 0
CMF_21 = sum(MFM_t * Volume_t) / sum(Volume_t), t in last 21 sessions
Return_20D = 100 * (AdjustedClose_t / AdjustedClose_{t-20} - 1)
```

`Demand_Proxy_Status` labels the result as accumulation proxy (`CMF_21 > 0` and return > 0), distribution proxy (both < 0), mixed, or unavailable (fewer than 21 sessions with High and Low). The label itself is not a separate score; the numeric technical `VOL` component below uses CMF, price return, and relative volume.

## 6. Numerical conventions

### 6.1 Rounding

All policy-relevant rounding uses `round_half_up()`:

```text
round_half_up(x, p) = Decimal(str(x)).quantize(10^-p, ROUND_HALF_UP)
```

This avoids Python/pandas banker-rounding ambiguity. Examples: `69.545 -> 69.55`; `69.455 -> 69.46` at two decimal places. Core scores are rounded to two decimal places. DCF and transcript intermediate stages are rounded to four decimals before becoming input to the next stage; published `Evidence_Score` and `Decision_Score` are rounded to two decimals.

### 6.2 Stable tie handling

Every important ordering uses stable `mergesort` and ticker symbol as the final ascending tie-break. Ranking is deterministic for equal score rows.

## 7. Core score architecture

This section describes the 4.x core score. Under Model 5 the number that is ranked is the factor model's research score (section 20); the 4.x scorer still runs because the policy needs its coverage, anomaly and specialist-model routing as evidence.

For each row:

```text
Fundamental_Score = clamp(Fundamental_Raw / 100 * 100, 0, 100)
Technical_Score   = clamp(Technical_Adjusted_Raw / 132 * 100, 0, 100)

Combined_Score = Core_Score
               = round_half_up(0.70 * Fundamental_Score
                             + 0.30 * Technical_Score, 2)
```

`Dynamic_Weight_Fund` and `Dynamic_Weight_Tech` are exported, but currently fixed at `0.70` and `0.30`; there is no volatility- or coverage-regime dynamic blend. ATR is already explicitly accounted for as a technical volatility component.

### 7.1 Fundamental model selection

| Sector / industry rule | Fundamental model |
|---|---|
| `Financial Services` + industry containing `BANK` | Bank Equity Quality Model |
| Financial Services + `CREDIT SERVICES`, `MORTGAGE`, or `CONSUMER FINANCE` | NBFC Equity Quality Model |
| Financial Services + `CAPITAL MARKET`, `ASSET MANAGEMENT`, `BROKER`, or `EXCHANGE` | Capital Markets Earnings Quality Model |
| Financial Services + `INSURANCE` | Insurance Equity Quality Model |
| Other Financial Services | Financial Services Data-Limited Model |
| `Real Estate` | Real Estate Asset Model |
| All other sectors | Generic Fundamental Model |

Financial Services and Real Estate are configured specialist sectors. A generic model or data-limited financial model for such a sector prevents BUY conviction.

### 7.2 Generic fundamental score: point grid (maximum 100)

Financial values expressed as ratios use `0.20 = 20%`; debt-to-equity is consumed in Yahoo's percentage-style unit. A missing or non-numeric input earns no points and also leaves the component's maximum, so the score is coverage-normalised and shrunk toward 50 (section 7.6): a missing input is unreported, not the worst value. The generic grid is:

| Component | Max | Exact score function |
|---|---:|---|
| PE (`PE`) | 15 | `0` if missing/nonpositive; `30% max` if `0 < PE < 1`; `15` if `<10`; `12.75` if `<18`; `10.05` if `<25`; `6` if `<40`; otherwise `3`. |
| PB (`PB`) | 8 | `0` if missing/nonpositive; `8` if `<2`; `6` if `<4`; `4` if `<8`; otherwise `2`. |
| ROE | 15 | `0` missing; `30% max` if `abs(ROE)>1`; max / `80%` / `55%` / `30%` / `10%` at ROE `>=20%`, `>=15%`, `>=10%`, `>=0`, negative. |
| ROA | 5 | `0` missing; `20% max` if `abs(ROA)>50%`; max / `80%` / `60%` / `30%` / `10%` at ROA `>=3%`, `>=2%`, `>=1%`, `>=0`, negative. |
| Debt to equity (`DE`) | 10 | `0` missing/negative; `10` if `<30`; `8` if `<70`; `5` if `<150`; otherwise `2`. |
| Current ratio (`CR`) | 7 | `0` missing/negative; `7` if `>=2`; `5` if `>=1.2`; `4` if `>=1`; otherwise `2`. |
| Profit margin (`PM`) | 10 | Same ladder as ROE with maxima at `>=20%`, `>=12%`, `>=5%`, `>=0`, negative; implausible `abs(margin)>100%` receives `30% max`. |
| Revenue growth (`RG`) | 10 | `0` missing; `30% max` if `>200%` or `<=-100%`; max / `80%` / `60%` / `30%` / `10%` at `>=20%`, `>=10%`, `>=5%`, `>=0`, negative. |
| Earnings growth (`EG`) | 10 | Same as revenue growth. |
| Dividend yield (`DY`) | 5 | `0` missing/nonpositive; `5` if `>=3%`; `4` if `>=1.5%`; otherwise `3`. Uses `Dividend_Yield_Ratio` when present. |
| EV/EBITDA (`EV`) | 5 | `0` missing/nonpositive; `5` if `<10`; `4` if `<18`; `2` if `<30`; otherwise `1`. |

#### ROE fallback

If reported ROE is unavailable, but EPS and positive book value are available and `EPS / Book_Value` lies in `[-1, 1]`, the scorer assigns:

```text
ROE = EPS / Book_Value
ROE_Source = "eps_to_book_proxy"
```

Otherwise the row retains reported ROE if available; `ROE_Source` is `reported`.

### 7.3 Specialist-model math

The point functions `PE`, `ROE`, `ROA`, `PM`, `DY`, and growth use the same general ladders above but with the documented maxima and, for several specialist growth components, a 15% maximum-growth threshold rather than 20%.

| Model | Components and maxima (sum = 100) |
|---|---|
| Bank Equity Quality | PE 10; PB-with-ROE 15; ROE 15; ROA 10; profit margin 5; revenue growth 8 (max at 15%); earnings growth 7; dividend 5; gross NPA 8; net NPA 7; capital adequacy 10. |
| NBFC Equity Quality | PE 10; PB-with-ROE 15; ROE 15; ROA 10; profit margin 5; revenue growth 10 (max at 15%); earnings growth 10; dividend 5; gross NPA 6; net NPA 5; capital adequacy 9. |
| Insurance Equity Quality | PE 15; PB-with-ROE 15; ROE 20; ROA 10; profit margin 10; revenue growth 10 (max at 15%); earnings growth 10; dividend 5; solvency 5. |
| Capital Markets Earnings Quality | PE 15; PB-with-ROE 15; ROE 20; ROA 10; profit margin 15; revenue growth 10 (max at 15%); earnings growth 10; dividend 5. |
| Financial Services Data-Limited | Same point layout as capital-markets model, but fails the dedicated-model eligibility policy. |
| Real Estate Asset | PE 15; PB-with-ROE 15; DE 15; CR 10; profit margin 15; revenue growth 15; earnings growth 15. |

The joint `PB-with-ROE` function avoids awarding a cheap price-to-book multiple where equity quality is poor. It first chooses a 20-point base from the joint conditions below and then scales proportionally: `points = round(base / 20 * model_max, 2)`.

| ROE condition | PB rule and base points |
|---|---|
| ROE < 0 | base = 1 |
| ROE >= 18% | PB `<=2`: 20; `<=3`: 16; otherwise 10 |
| ROE >= 15% | PB `<=1.5`: 17; `<=2.5`: 14; otherwise 8 |
| ROE >= 12% | PB `<=1.25`: 14; `<=2`: 11; otherwise 6 |
| ROE >= 10% | PB `<=1`: 10; `<=1.5`: 8; otherwise 4 |
| otherwise nonnegative ROE | PB `<1`: 4; otherwise 2 |

It returns zero when PB is missing/nonpositive or ROE is missing.

For bank/NBFC risk points, the model infers percentage units when `abs(Capital_Adequacy) <= 1`, then multiplies NPA and CAR ratios by 100. Bank good levels are gross NPA <= 2% and net NPA <= 1%; NBFC good levels are <= 3% and <= 1.5%. For both:

```text
NPA points = max                         if NPA <= good threshold
           = round(0.70 * max, 2)        if NPA <= 4% gross / 2% net
           = round(0.35 * max, 2)        if NPA <= 8% gross / 4% net
           = 0                           otherwise

CAR points = max                         if CAR >= 18%
           = round(0.80 * max, 2)        if CAR >= 15%
           = round(0.50 * max, 2)        if CAR >= 12%
           = 0                           otherwise
```

Real-estate leverage/liquidity functions are:

```text
DE points = 15 if DE < 30; 12 if <70; 7 if <120; else 3; 0 if missing/negative
CR points = 10 if CR >=1.5; 7 if >=1.0; else 3; 0 if missing/negative
```

Insurance earns its five solvency points only at `Solvency_Ratio >= 1.5`.

### 7.4 Sector-relative fundamental scoring

The generic model can blend absolute points with same-sector cross-sectional percentile points. It applies to PE, PB, ROE, ROA, DE, CR, margin, revenue growth, earnings growth, dividend yield, and EV/EBITDA.

For each metric, only rows that are fundamental-record available, non-stale, non-anomalous (fewer than two anomalies), and in a known sector can form the peer distribution. Invalid valuation multiples (`PE/PB/EV <= 0`) and invalid DE/CR are excluded from applicable distributions. At least `MIN_SECTOR_PEERS=5` eligible same-sector values are required.

For average tie rank `r` among `n` peers:

```text
percentile = (r - 1) / (n - 1)
relative_score = max_points * percentile                  # higher-is-better metric
relative_score = max_points * (1 - percentile)            # lower-is-better metric
```

The best and worst members therefore map symmetrically to the full range `[max_points, 0]` rather than pandas' asymmetric percentile endpoint. With default sector weight `w=0.5`:

```text
component_points = round(absolute_points * (1 - w)
                       + relative_score * w, 2)
```

The result falls back to absolute scoring if peer evidence is unavailable. Post-blend hard guards below always prevail.

### 7.5 Fundamental anomaly and value-trap guards

The anomaly detector flags:

- `0 < PE < 1`
- `abs(ROE) > 100%`
- `abs(ROA) > 50%`
- `abs(Profit_Margin) > 100%`
- revenue or earnings growth `> 200%` or `<= -100%`

Hard post-blend component caps are: PE < 1 -> 4.5; low PB with missing/ROE < 10% -> 4.0; extreme ROE -> 4.5; extreme ROA -> 1.0; extreme margin -> 3.0; extreme growth -> 3.0. If both revenue and earnings are negative, the value-trap guard also caps PE below 15 at 8 and PB below 2 at 5.

Two or more anomalies are a BUY-level policy failure; one or more anomaly prevents STRONG BUY.

### 7.6 Fundamental coverage and specialist quality

Coverage is an evidence completeness ratio, not a sum of points:

```text
Fundamental_Coverage = available expected model fields / expected model fields
```

Expected field counts: generic 11; bank/NBFC 8; insurance 6; capital markets 8; data-limited financial 6; real estate 7. `Data_Quality` is `FULL` at coverage >= 0.80, `LIMITED` at >= 0.50, otherwise `LOW`.

Specialist high-conviction checks are:

- Bank/NBFC: Gross NPA, Net NPA, and CAR all available; gross NPA <= 8%, net NPA <= 4%, CAR >= 12%.
- Insurance: solvency available and >= 1.5.
- Capital Markets: ROE, ROA, and profit margin available.
- Financial Services Data-Limited: always ineligible because a dedicated model is required.

## 8. Technical evidence and score mathematics

### 8.1 Indicator construction

All score-driving indicators use adjusted OHLC and `Technical_Price` on the same scale.

| Feature | Construction |
|---|---|
| RSI(14) | Wilder EWMA of gains/losses, `alpha=1/14`; `RSI=100-100/(1+avg_gain/avg_loss)`. All gain -> 100; all-flat -> 50. |
| MA20 / MA50 | Rolling adjusted close means; MA50 slope is `100 * (MA50_now / MA50_20_sessions_ago - 1)`. |
| MACD | `EMA_12(close)-EMA_26(close)`, signal is `EMA_9(MACD)`. |
| Bollinger position | `BB_Position=(Technical_Price-BB_lower)/(BB_upper-BB_lower)` using 20-period mean and 2 standard deviations; zero range -> 0.5. |
| ADX / DI | Wilder true range, +/- directional movement and `alpha=1/14` smoothing. `+DI=100*smoothed(+DM)/ATR`, `-DI=100*smoothed(-DM)/ATR`, `DX=100*abs(+DI--DI)/(+DI+-DI)`, ADX is Wilder EWMA of DX. |
| StochRSI | 14-period RSI position inside rolling RSI min/max, then 3-period mean. |
| ATR(14) | Wilder EWMA of true range `max(H-L, abs(H-prevClose), abs(L-prevClose))`. |
| 1/3/6 month return | `100 * (AdjustedClose_now / AdjustedClose_{lookback} - 1)` at 21 sessions, 65 sessions, and all available prior sessions. |
| 1 session return | The same formula at a 1-session lookback, exported as `Pct_Change_1D`. Display evidence only: no score component, gate, or rank reads it. It is on adjusted closes like every other return here, so an ex-dividend or split session reports the holder's return rather than the mechanical price cut. Added in output schema `4.2.0`; it is a required price-cache column so a cache written before it existed forces one refresh rather than reusing rows that would blank the whole column. |
| Relative volume | `Vol_Ratio = last_volume / rolling_mean_20(volume)`. |

Missing indicators remain missing; valid zero values are observed data. For example, a flat but sufficiently long time series has ADX/DI/ATR zero rather than missing.

### 8.2 Technical component functions (raw maximum 132)

Every interpolation uses endpoint-clamped linear interpolation (`np.interp`). The following table specifies knots as `(input -> points)`.

| Component | Max | Input and exact point function |
|---|---:|---|
| RSI | 12 | RSI knots: `0→3, 20→4, 30→8, 40→11, 50→12, 60→11, 70→8, 80→5, 100→3`. |
| MA20 | 15 | `d20=100*(Technical_Price/MA20-1)`; knots `-30→3, -10→5, -5→7, 0→10, 5→13, 7.5→15, 15→11, 30→8`. |
| MA50 | 15 | `d50=100*(Technical_Price/MA50-1)`; distance knots `-30→2, -15→4, -5→7, 0→10, 5→13, 8→15, 15→11, 35→7`; add slope interpolation `-10→-6, -3→-6, 0→0, 3→2, 10→2`; clamp final `[1,15]`. |
| MACD | 15 | `spread=100*(MACD-MACD_Signal)/Technical_Price`; knots `-3→3, -1→5, 0→8, 0.5→12, 2→15, 5→15`. |
| Volume/demand (`VOL`) | 15 | Formula immediately below. |
| Momentum (`MOM`) | 20 | 1-month return knots `-30→1, -10→2, -5→6, 0→8, 5→20, 15→20, 25→14, 40→8, 80→4`. |
| Bollinger (`BB`) | 8 | BB position knots `-0.5→5, 0→7, 0.15→8, 0.3→6, 0.7→6, 0.9→5, 1→3, 1.5→2`. |
| ADX | 12 | Formula immediately below. |
| StochRSI | 12 | exactly <=0 or >=100 -> 6; `<20` with negative ADX direction -> 6; otherwise knots `0→10, 15→12, 30→8, 50→8, 70→8, 80→6, 100→3`. |
| ATR | 8 | `atr_pct=100*ATR_14/Technical_Price`; knots `0→8, 0.5→8, 1→7, 2→5, 4→2, 6→1, 10→0`. |

The continuous volume/demand component requires CMF, 20-day adjusted-price return, and nonnegative relative volume:

```text
c = tanh(CMF_21 / 0.10)
r = tanh(Return_20D_Pct / 10)
d = (c + r) / 2
v = tanh(Vol_Ratio / 1.50)
VOL_points = clamp(7.5 + 7.5 * d * v, 0, 15)
```

Thus high volume amplifies directional confirmation rather than automatically receiving a reward; high-volume distribution can score below neutral.

For ADX:

```text
direction = (+DI - -DI) / (abs(+DI) + abs(-DI))      # 0 if denominator is zero
strength  = clamp((ADX - 15) / 25, 0, 1)
ADX_points = clamp(3 + 9 * strength * direction, 1, 12)
```

### 8.3 Technical coverage and confidence shrinkage

A component is observed only if all its prerequisites are valid. Let `M_i` be the maximum points of observed component `i`, `S_i` its actual points, and `M_total=132`:

```text
Observed_Max            = sum(M_i for observed components)
Technical_Coverage      = Observed_Max / 132
Technical_Observed_Score = 100 * sum(S_i) / Observed_Max     if Observed_Max > 0
                           50                                otherwise

Technical_Score = clamp(50 + Technical_Coverage
                            * (Technical_Observed_Score - 50), 0, 100)
```

An empty technical row is exactly neutral (`Technical_Score=50`) but has zero coverage. Partial evidence moves only proportionally away from 50. This differs from assigning arbitrary neutral component points, and coverage gates prevent sparse-but-high partial evidence from qualifying as BUY.

## 9. Reverse-DCF evidence

### 9.1 Purpose and scope

`ReverseDCFModel` produces valuation evidence; it never sets final ratings/ranks. It models an equity-value proxy using reported positive FCF, market capitalization, a fixed discount rate and terminal growth, then reports the growth/terminal assumptions implied by the current market cap.

Financial Services and Real Estate are explicitly unsupported because a generic FCF model is not treated as a suitable specialist valuation model.

### 9.2 Assumptions and base-case DCF

Defaults: five forecast years `N=5`, discount rate `r=11%`, terminal growth `g_T=4%`, allowed implied growth range `[-30%, 60%]`, allowed terminal-growth range `[-5%, min(9%, r-0.1%)]`.

Base expected growth uses a sector benchmark plus a size adjustment, clamped to 5%-25%. Sector benchmarks are Technology 18%, Communication Services/Healthcare 16%, Consumer Cyclical 15%, Industrials 14%, Financial Services 13%, Basic Materials/Real Estate 12%, Energy/Consumer Defensive 10%, Utilities 8%, and 15% fallback. Size adjustment is `-3%` for market cap >= 200,000 crore, `-1.5%` >= 20,000 crore, 0 >= 5,000 crore, else `+2%`. These thresholds are in rupees (market cap divided by 10 million); a US run applies the same numbers to dollar market caps.

For base FCF `FCF_0`, forecast growth `g`, terminal growth `g_T`, and discount rate `r`:

```text
FCF_t = FCF_{t-1} * (1 + g)
PV_forecast = sum(FCF_t / (1+r)^t, t=1..N)
Terminal_Value_N = FCF_N * (1+g_T) / (r-g_T)
DCF_Value = PV_forecast + Terminal_Value_N / (1+r)^N
```

Under Model 5 the DCF score is an input to the Value block and the separate DCF blend stage has weight zero (section 20.2); the 4.x path blends it at `REVERSE_DCF_RANKING_WEIGHT=0.10`. The model requires positive reported FCF for blending. Missing FCF with positive revenue can create an 8%-of-revenue estimated FCF audit scenario, but it is not blend-eligible. Reported nonpositive FCF is preserved as `negative_fcf`, review-required, and not silently replaced with the revenue-margin estimate.

### 9.3 Reverse solves and value score

The model solves two monotonic equations with 80 iterations of bisection:

```text
find implied FCF CAGR g such that DCF_Value(FCF_0, g, fixed g_T, r, N) = Market_Cap
find implied terminal growth g_T such that DCF_Value(FCF_0, expected g, g_T, r, N) = Market_Cap
```

A target outside a configured range is exported as `below_range` or `above_range` with a censored bound; it is not falsely represented as an exact endpoint.

The policy evidence comes from a single base-case relationship:

```text
q = DCF_Base_Case_Value / Market_Cap
DCF_Valuation_Score = round_half_up(
    clamp(50 + 50 * tanh(log(q) / scale), 0.01, 99.99), 2)
```

Default `scale=1.0`. A ratio of one is 50; reciprocal gaps produce symmetric scores around 50. The direction is favorable if `log(q) > 0.05`, adverse if `< -0.05`, otherwise neutral.

`DCF_Blend_Eligible=True` requires a supported sector, positive market cap, reported positive FCF, successful base calculations, and a valid direction. Estimated/missing/unsupported data receives score 50 with zero blend weight. Low reported FCF yield can remain reliable adverse evidence, but reported negative FCF prevents STRONG BUY by default.

## 10. Transcript sentiment evidence

Two scores describe an earnings call. The **tone** score measures how the call sounds (word lists, a language model for finance text). The **outlook** score measures what management said about the future (guidance, order book, demand, margins). Both are computed outside the daily run and stored; the daily screener only reads them. Transcripts are used on NSE; the US run switches them off (`TRANSCRIPT_SENTIMENT_ENABLED=False`).

### 10.1 Upstream transcript analysis

Transcripts come from two sources: the company\'s filed transcript, which arrives days after the call, and a speech-to-text transcript of the call recording, made the evening of the call. The recording is fetched by the Earnings call recordings workflow (`workers/call_recordings.py`), transcribed in pieces with `faster-whisper`, and stored as an ordinary transcript whose document\'s `extraction_method` starts `speech:`. When the filed transcript arrives it deletes the recording\'s, so the recording never becomes the call\'s "previous quarter". The speech text has no speaker labels, so the tone score reads it as one voice. Everything below applies to both sources. A call filed twice keeps the longer text and the shorter copy and its scores are removed, so a duplicate is neither scored twice nor read as its own previous quarter.

A separate transcript worker discovers, extracts, cleans, segments, chunks, analyzes, and stores call sentiment. The daily screener only bulk-loads the latest cached record from Supabase, scoped to the market; it does not download or re-analyze every transcript. FinBERT is required in the transcript and recording workflows and switched off in the daily screener, which only reads stored rows.

Each chunk uses financial lexicons, TextBlob polarity, and optional FinBERT. If FinBERT is available:

```text
sentiment_signal = 0.70 * FinBERT_score
                 + 0.20 * lexical_balance
                 + 0.10 * TextBlob_polarity
```

Without FinBERT:

```text
sentiment_signal = 0.55 * lexical_balance + 0.45 * TextBlob_polarity
optimism = clamp(50 + 50 * sentiment_signal, 0, 100)
```

Other chunk features include:

```text
risk_intensity = clamp(45 + 7*negative_hits + 6*uncertainty_hits
                         + 5*constraint_hits - 4*positive_hits, 0, 100)
management_confidence = clamp(optimism + 4*strong_modal_hits
                               - 5*weak_modal_hits - 40*uncertainty_density
                               + 12 if raised guidance else 0, 0, 100)
analyst_pressure = clamp(25 + 8*question_count + 4*uncertainty_hits
                          + 3*negative_hits + 10 if analyst question else 0, 0, 100)
answer_quality = clamp(45 + min(35, 3*sentence_count)
                       + 10 if management answer else 0, 0, 100)
```

Weighted transcript aggregates use estimated token count as the weight. The stored overall (tone) score is:

```text
Overall_Transcript_Score = 0.25 * optimism
                         + 0.20 * management_confidence
                         + 0.20 * guidance_strength
                         + 0.20 * (100 - risk_intensity)
                         + 0.15 * answer_quality
```

Explicit guidance is categorical and conservative: lowered guidance dominates raised guidance, which dominates maintained guidance when present in different chunks.

### 10.2 Daily eligibility, decay, and weight

A transcript is score-eligible only if it belongs to the current reporting cycle, is not older than `TRANSCRIPT_MAX_EVIDENCE_AGE_DAYS=180`, and has nonzero weight. The raw recency factor is:

```text
w_age = exp(-ln(2) * age_days / half_life_days)          # default half life = 90 days
```

It is tapered before the next reporting-cycle transition:

```text
w_cycle = clamp(days_until_next_transcript_deadline / taper_days, 0, 1)
w_evidence = w_age * w_cycle                             # default taper = 20 days
Transcript_Blend_Weight = TRANSCRIPT_SENTIMENT_WEIGHT * w_evidence      # weight 1.0 in production
```

The tone score and the outlook score share this one weight, split 15/85 (section 10.3 and 11.1). The exported `Transcript_Weighted_Score = 50 + (Transcript_Score - 50) * w_evidence` is an audit feature. The central policy uses `Transcript_Effective_Score` (the current-cycle stored score) plus the already-decayed blend weight.

Quality eligibility is an audit/high-conviction check, not a second numerical score:

```text
Transcript_Quality_Eligible = current-cycle eligible
                           AND Transcript_Score >= 55
                           AND (risk missing OR risk <= 60)
                           AND guidance != "lowered"
```

Missing, expired, prior-cycle, unconfigured, or unavailable transcripts are neutral; they do not receive a hidden rank tier. A fresh call whose outlook has not been extracted yet is also unreported until it is (section 11.1). By default, a transcript is not required for STRONG BUY (`REQUIRE_TRANSCRIPT_FOR_STRONG_BUY=False`).

### 10.3 Outlook

`sentiment/outlook.py` asks a language model to extract the forward-looking statements of a call: guidance raised, lowered or maintained, growth ranges, order book, capacity, demand, margins, tailwinds and headwinds. An item counts only if the model also returns a quote and that quote is found in the transcript; unverified items are cleared. The score is:

```text
Outlook_Score = clamp(50 + sum(points of verified items), 0, 100)
```

Examples of the points: guidance raised +15, lowered -20, maintained +3; order book +/-8; demand +8/-10; margin +6/-8; tailwind +2; headwind -3. The score is attached only when it belongs to the same call date as the tone record and at least one item was verified; otherwise the column stays empty rather than 50. The extraction carries a version string (`outlook-v1`) and the name of the model that made it.

In production the request goes to OpenRouter (model `z-ai/glm-5.3-flash`, temperature 0, strict JSON schema, minimal reasoning, price-capped routing); on a developer\'s machine it goes to Token Harbor\'s free model, and those readings are printed, never stored. Production refuses Token Harbor and a missing free key is an error, never a fallback to the paid provider. The scorer reads the latest outlook of any model unless `TRANSCRIPT_OUTLOOK_MODEL` names one. Extraction runs after the transcript worker and after each recording batch, with a spend cap per run, and is skipped with a warning when no key is set.

The stance word on the dashboard\'s Concalls page is this outlook score read into a band (bullish from 72, optimistic 62, neutral 53, cautious 45, bearish below). It is display only.

## 11. Authoritative evidence blend and recommendation policy

`screener/recommendation.py` is the only writer of canonical decisions (`Rating`, `Rank`, `Buy_Eligible`, `Final_Score`, and the rest). The scoring layer emits components and `Core_*` diagnostics only.

### 11.1 Stage equations

The finalizer begins with `Combined_Score` and writes `Core_Score`. Under Model 5 that is the research score, itself a run percentile of the five factor blocks (section 20.3). On the 4.x path it is the 70/30 blend. Each stage below is rounded to four decimals and the exported value is the next stage\'s input, so the CSV arithmetic reproduces exactly.

**Stage 1, reverse DCF.** Applied symmetrically around neutral 50:

```text
Score_After_DCF = clamp(Core_Score + w_dcf * (DCF_score - 50), 0, 100)
```

Only `DCF_Blend_Eligible` rows with valid score and positive weight receive the adjustment. On the 4.x path `w_dcf=0.10`. Under Model 5 the DCF score is already a Value input and `w_dcf` is 0, so `Score_After_DCF = Core_Score`.

**Stage 2, the earnings call.** A call moves the score both ways. Tone and outlook are each measured against the median call of the run: management is upbeat by default (94% of scored calls sat above 50 on 6 October 2026), so against 50 every covered company would gain simply for having held a call. Against the median, about half the covered companies gain and half lose, and a company with no usable call is untouched.

```text
tone_signal    = Transcript_Effective_Score - tone_median
outlook_signal = Outlook_Score - outlook_median
signal         = 0.15 * tone_signal + 0.85 * outlook_signal       call has an outlook
signal         = tone_signal                                      outlook switched off or share = 0
transcript_delta = Transcript_Blend_Weight * signal               weight 1.0 x age/cycle factor (section 10.2)
```

The 15/85 split is `TRANSCRIPT_OUTLOOK_SHARE=0.85`, decided in one place, `RecommendationPolicy._outlook_share`. Each median is taken over the calls scored in the run; with fewer than `TRANSCRIPT_NEUTRAL_MIN_CALLS=30` the centre is 50. A point of outlook above the median call therefore adds about 0.85 of a point to the score. `TRANSCRIPT_TWO_SIDED=false` restores the older rule that applied only the negative half of the signal.

**A call waits for its outlook.** The outlook is extracted hours after the transcript lands. While it is missing, and the outlook share is above zero, the call is not evidence: `Transcript_Awaiting_Outlook=True` and the company is scored as if it held no call until the first run after the outlook is stored. Read on tone alone in between, a cut in guidance scored as upbeat (HINDZINC, 23 October 2026: tone 78.6, outlook 41, rank 131 lifted to 18).

**Stage 3, the published score.**

```text
Evidence_Score_Raw = Score_After_DCF + transcript_delta                    (not clipped)
Evidence_Score     = run percentile of Evidence_Score_Raw                  Model 5
Evidence_Score     = clamp(Evidence_Score_Raw, 0, 100)                     4.x path
```

On a Model 5 run `Evidence_Score` is therefore the percentile, across that day\'s universe, of the research score plus the DCF and call adjustments. The call is part of that percentile, while the five block percentiles (`Quality_Percentile` and the rest) and `Research_Score` are computed before the call and do not include it. Ranking the sum once, instead of clipping it at 100, keeps names the call lifted past the top from tying at 100 (35 names did on 23 October 2026): only the strongest name reads 100 and `>= 70` stays the top 30%. The call keeps its reach in research points, the scale its weight was measured on.

### 11.2 Rating bands

| Score band | Rating |
|---:|---|
| >= 70 | STRONG BUY |
| >= 60 and < 70 | BUY |
| >= 50 and < 60 | HOLD |
| >= 40 and < 50 | REDUCE |
| < 40 | SELL |
| missing | UNRATED |

Under Model 5 the score is a percentile, so the bands are relative: STRONG BUY is the top 30% of the run, BUY the next 10%, and about 40% of rows read REDUCE or SELL whatever the market does. What stops "the top 30% of a collapsing market" from being published as STRONG BUY is the set of absolute gates below.

### 11.3 BUY gates

Any BUY failure sets the policy ceiling to `59.99`. The gates are of two kinds.

**Evidence-quality gates (both models).** Bad evidence is not a research view, so these always cap:

1. Core score unavailable.
2. Any present coverage flag (`Coverage_Eligible`, fundamental coverage eligibility, technical coverage eligibility) is false.
3. `Data_Quality == LOW`.
4. Specialist model required but unavailable/data-limited.
5. Stale fundamental fallback.
6. The price bar is behind the expected session (`REQUIRE_ALIGNED_PRICE_BAR_FOR_BUY`).
7. At least two fundamental anomalies.
8. A dedicated financial model\'s specialized regulatory/quality evidence is ineligible.

**Policy gates.** Model 5 (production) applies the trend, relative-strength, factor-percentile, coverage, liquidity and regime gates of section 20.5. The 4.x path applies the uptrend test instead: when `REQUIRE_UPTREND_FOR_BUY=True` it fails on adjusted price or MA50 unavailable, `Technical_Price <= MA50`, MA50 slope unavailable or `< 0.0`, or three-month return unavailable or `<= 0.0`.

### 11.4 STRONG BUY gates

STRONG BUY inherits all BUY failures. Any remaining failure sets the ceiling to `69.99`. Both models require:

1. Fundamental coverage >= 0.75 and technical coverage >= 0.90 when numeric coverage is present.
2. Specialized quality is eligible.
3. No fundamental anomaly at all.
4. By default, `DCF_Status != negative_fcf`.
5. If configured, a fresh quality transcript (`REQUIRE_TRANSCRIPT_FOR_STRONG_BUY`, off in production).

The 4.x path adds growth of at least 5%, ADX >= 20, `+DI > -DI` and `Technical_Score >= 55`. Model 5 adds the percentile and moving-average conditions of section 20.5 instead, because counting both would double-count the trend requirement.

The policy collects every simultaneous failure, de-duplicates it, and exports JSON arrays, semicolon text, and counts. This makes a rating cap explainable rather than simply showing one first failure.

### 11.5 Ceiling and final decision

```text
Decision_Score_Ceiling = 59.99  if any BUY failure
                       = 69.99  if no BUY failure but any STRONG BUY failure
                       = 100.00 otherwise

Policy_Capped_Score = round_half_up(min(Evidence_Score, Decision_Score_Ceiling), 2)
Decision_Score      = round_half_up(min(Evidence_Score, enforced ceiling), 2)
Final_Score         = Decision_Score
Rating              = rating_from_score(Decision_Score)
```

By default (`APPLY_RATING_CAP=True`) the enforced ceiling is the policy ceiling, so `Decision_Score = Policy_Capped_Score` and `Policy_Eligible_Rating` equals `Rating`. With `APPLY_RATING_CAP=False` on a factor-model run only the evidence-quality gates of section 11.3 cap the published rating; `Policy_Eligible_Rating` and `Decision_Score_Ceiling` still show what the policy gates alone would have done.

`Evidence_Rating` (also `Research_Rating`) is the band of the uncapped `Evidence_Score`. A DCF or call contribution can lift `Evidence_Score`, but it cannot resurrect a candidate that failed an independent gate.

### 11.6 Stability diagnostics

The finalizer exports continuous distance-to-boundary diagnostics, including:

```text
Buy_Price_MA50_Margin_Pct        = 100 * (Technical_Price / MA50 - 1)
Buy_MA50_Slope_Margin_Pct        = MA50_Slope_Pct - 0
Buy_3M_Return_Margin_Pct         = Pct_Change_3M - 0
Strong_Buy_Growth_Margin_Ratio   = max(Revenue_Growth, Earnings_Growth) - 0.05
Strong_Buy_ADX_Margin            = ADX_14 - 20
Strong_Buy_DI_Margin             = ADX_Plus_DI - ADX_Minus_DI
Strong_Buy_Technical_Score_Margin = Technical_Score - 55
```

It similarly exports BUY/STRONG-BUY fundamental and technical coverage margins and distance to the nearest score threshold `{40, 50, 60, 70}`. Borderline bands are audit-only; default bands include score 1 point, price-vs-MA50 1%, MA50 slope 0.25 points, 3M return 1%, growth 1 percentage point, ADX/DI 1 point, technical score 2 points, and coverage 0.05.

`Decision_Stability_Status` precedence is:

```text
DATA_LIMITED -> insufficient required coverage or missing evidence score
BORDERLINE   -> relevant near-boundary reason exists
POLICY_CAPPED -> decision ceiling reduced score
CLEAR        -> none of the above
```

## 12. Rank semantics and how the top stocks are selected

The application exposes several intentionally distinct answers rather than treating one rank as universal.

| Field | Sort order | Meaning |
|---|---|---|
| `Core_Score_Rank` | `Combined_Score DESC`, `Symbol ASC` | Pre-evidence diagnostic order. |
| `Score_Rank` | `Evidence_Score DESC`, `Symbol ASC` | Uncapped research-evidence order. |
| `Recommendation_Rank` | rating class (STRONG BUY → BUY → HOLD → REDUCE → SELL → UNRATED), `Decision_Score DESC`, `Evidence_Score DESC`, symbol | Published recommendation-class ordering. |
| `Investment_Rank` | Model 5: `Evidence_Score DESC`, `Research_Score DESC`, `Gate_Severity ASC`, `Symbol ASC`. 4.x: `Decision_Score DESC`, `Evidence_Score DESC`, `Symbol ASC` | **Primary investment/research rank.** |
| `Rank` | alias of `Investment_Rank` | Backward-compatible main rank. |
| `Action_Rank` | `Action_Score DESC` | Published only when `TIMING_WEIGHT` is above zero (it is 0 in production, so the column is absent); stage and relative-strength rating are shown as display evidence. |
| `Actionable_Rank` | `Portfolio_Actionable DESC`, `Investment_Rank ASC` | Execution-oriented presentation rank. |

The top stocks shown by the main CSV/report are `Rank=1...TOP_STOCKS_COUNT` in primary investment order. Under Model 5 the gates label and rate a stock but do not rank it: ranking by `Decision_Score` would sort a column that is constant for every capped name (they share one ceiling) and fall through to the ticker, which is alphabetical order presented as investment merit, and ranking by eligibility class first cost 5-16 CAGR points in every point-in-time window where the gates bound. `Gate_Severity` only breaks ties between equal scores. A stock with high evidence that fails a BUY gate therefore keeps its place by merit and carries a capped rating and its gate reasons; `RANK_BY_ELIGIBILITY_CLASS=true` would sort eligibility first.

The final execution overlay preserves investment rank inside the actionable/non-actionable buckets. It never uses transcript availability or liquidity as a hidden tie-break for primary rank.

## 13. Liquidity and portfolio actionability

### 13.1 Official NSE evidence

The provider downloads/caches NSE's monthly CM security category/mean-impact-cost file for EQ symbols. It recognizes Groups I, II, and III. Group I is treated as the liquid category and the official impact-cost reference order is Rs1 lakh.

The category file is cached (`NSE_LIQUIDITY_CACHE_MAX_AGE_DAYS`, 35 days). A failed refresh falls back to the stale cache and says so ("Stale cache"), a file with fewer than 500 EQ records is rejected, and `NSE_LIQUIDITY_ENABLED` switches the provider off. A BSE-only symbol (`.BO`) never matches an NSE row, so it reads "No EQ category" and is judged on the turnover proxy. The US has no provider, so its liquidity columns rely on the proxy alone.

### 13.2 Position-capacity calculation

For configured position target `P` (default Rs100,000) and participation rate `p` (default 1%):

```text
Max_One_Day_Order = Median_Turnover_20D_INR * p
Turnover_Proxy_Build_Days = ceil(P / Max_One_Day_Order)
```

Definitions:

```text
official_direct_evidence = NSE category = Group I
                        AND impact cost present and <= 1%
                        AND P <= Rs100,000
turnover_fits = Max_One_Day_Order >= P
frequency_ok  = Trading_Frequency_60D >= 0.80
concentration_ok = Turnover_Top5_Share_60D <= 0.50
```

A row is actionable if:

```text
official_actionable = Group I AND (official_direct_evidence OR (turnover_fits AND concentration_ok))
fallback_actionable = no official category AND turnover data present
                      AND turnover_fits AND frequency_ok AND concentration_ok
Portfolio_Actionable = official_actionable OR fallback_actionable
```

For a Group I candidate with direct Rs1 lakh impact-cost evidence and a target no larger than Rs1 lakh, effective build days are set to one rather than applying the conservative 1% turnover proxy. Group II/III are restricted and never receive the turnover fallback, which applies only when there is no official category. If official evidence is absent, turnover-based actionability is explicitly identified as a proxy. Configured participation is clamped to 0.0001-1 and the frequency and concentration thresholds to 0-1.

Actionability does not enter the score or the rank: it determines `Portfolio_Actionable` and `Actionable_Rank`. Under Model 5 it also feeds one BUY gate (`REQUIRE_LIQUIDITY_FOR_BUY`, section 20.5), and the research view (`Research_Rating`) stays uncapped.

### 13.3 Liquidity prefilter

The prefilter requires either Group I or, when official category is unavailable, both average and 20-day median turnover at or above the floor (`MIN_AVG_TURNOVER_INR`; Rs50 lakh/day by default). It also requires raw current price >= configured minimum (default zero). It is off in the NSE run, so liquidity does not choose the research universe there. It is on in the US run, where the floor is 1,000,000 dollars a day, because the US has no official liquidity category. Where it is on, the evaluated research universe is smaller; the run manifest records whether it was used.

### 13.4 Recently listed stocks

A listing is unscored until it has 60 sessions of history and clears the liquidity floor. `workers/new_listings.py` (a step of the Financial statements workflow, NSE only, since the US has no listing date) writes one row per such mainboard listing to `new_listings`, replaced on every run, with the reason (`insufficient_history`, `below_liquidity_floor`, `no_price_data`, `pending_run`). It never scores: these names are not in `screener_snapshot`, so no rank, tile or export includes them. The dashboard shows them as "Not rated".

## 14. Optional non-scoring overlays

### 14.1 Red flags

When enabled, `RedFlagEnricher` joins cached data such as issuer/trading severity, flag count, pledge/encumbrance fields, and source freshness. `RedFlagShadowSimulator` produces a hypothetical outcome **if the underlying evidence is confirmed**:

- severity 2 issuer/trading can cap a hypothetical rating at BUY;
- severity >= 3 can cap a hypothetical rating at HOLD;
- issuer severity >= 3 clips hypothetical score to at most 59.99.

The rules apply only where `Red_Flag_Status == "Available"`, that is, when the stored snapshot is fresh (stale after 7 days); stale or partial rows get only the action text "Stale/partial evidence; refresh before review". The simulator also exports `Shadow_Red_Flag_Review_Required` (severity >= 2) with an action and a "would change" flag. Enrichment is off by default, on in the NSE run and off in the US run; the feed is built by `workers/red_flag_worker.py` from `red_flags/vigil.py`.

These are `Shadow_*` fields only. Live `Rating`, `Final_Score`, and ranks remain unchanged because the feed is discovery evidence requiring primary-source verification.

### 14.2 News and FII/DII

After final ranking, the application fetches Google News RSS headlines for only the top `NEWS_SENTIMENT_TOP_N` rows (default 20). It counts fixed positive/negative whole-word lexicon hits and exports a display label. News does not feed the score.

FII/DII is presently an explicit placeholder and is logged, not scored. Earnings-surprise consensus is absent rather than approximated.

## 15. Output, observability, and reproducibility

### 15.1 Files and delivery

The standard run produces the files below, for either market (the US workflow writes the same files with `MARKET=US`). The workflow uploads the CSV, manifest, HTML and PDF as the run artifact for 7 days; the diagnostics JSON stays on the runner.

| Artifact | Purpose |
|---|---|
| `advanced_analysis_YYYYMMDD.csv` | Full ranked research universe with audit fields. |
| `advanced_analysis_YYYYMMDD.manifest.json` | Reproducibility manifest for the CSV. |
| `collection_diagnostics_YYYYMMDD.json` | Selected/collected/missing symbol sets, source state, calendar, and collection metadata. |
| `dashboard_*.html`, `stock_report_*.pdf` | Standalone HTML report from `InteractiveDashboard` and the PDF report, retained in the workflow artifact. |
| Supabase dashboard read model | Written by the publisher: `screener_runs`, current full `screener_snapshot` rows, narrow long-lived `screener_history` rows, `estimate_history`, `universe_index` and `valuation_basis`, consumed by the private web application. |
| Optional email/WhatsApp | Delivery layers; disabled by default. Only a scheduled run emails. |
| Production market-data cache | The original five paths: `price_cache.csv`, `fundamental_cache.csv`, `nse_liquidity_categories.csv`, `backtest_history.csv`, and `yfinance_cache/`. |
| `statement_cache.csv` | Annual-statement input, stored in a separate production cache namespace rather than the market-data composite. |
| Backtest history | Model-version-separated monitoring log when writes are enabled; it remains one of the five production composite-cache paths. |

### 15.2 Run manifest

`validation/reproducibility.py` builds a canonical secret-free manifest containing:

- schema version, UTC timestamp, Git SHA, dirty-worktree/status/diff hashes;
- the model version (the policy and schema versions are part of the hashed configuration);
- SHA-256 of an allow-listed effective configuration, which includes the market and its universe source, so runs on different exchanges never share a hash;
- hashes/sizes of cache inputs and outputs;
- Python/platform/package versions;
- collection diagnostics and exact collection counts.

The CSV also carries run-level fields such as model/config hash, Git SHA, universe-source hash, market calendar version, and collection diagnostics hash.

### 15.3 Backtest boundary

`BacktestEngine` (in `screener/market_data.py`) is a monitoring log, not a backtest. It records each run\'s ratings and later realized returns within one `MODEL_VERSION`, entering at the close that produced the score, which a real trade could not do. It does not solve survivorship bias, benchmark comparison, transaction costs or delistings.

Point-in-time testing lives in the separate `backtest/` package, run with `python -m tools.run_p0_backtest`. A signal forms on the close of day t and fills at the open of t+1; returns are adjusted for corporate actions and net of Indian charges; delisted securities stay in; and the package replays production\'s own `FactorModel`. It must never read anything the model could not have seen on the simulated day. It reads two local archives that are not in git: `reports_advanced/backtest` (NSE filings, ending at the FY2024 annual and December 2024 quarterly filings, because NSE\'s results endpoint thins out after early 2025) and `reports_advanced/backtest_ext` (the same plus later periods taken from stored vendor statements, written by `python -m tools.extend_fundamental_panel`). Pass `--root reports_advanced/backtest_ext` for any window past mid-2025. Section 20.9 gives the results and their limits.

### 15.4 GitHub Actions cache and validation isolation

The production composite cache keeps its original five-path declaration exactly: `price_cache.csv`, `fundamental_cache.csv`, `nse_liquidity_categories.csv`, `backtest_history.csv`, and `yfinance_cache/`. GitHub incorporates the declared path list into an internal cache version, so adding `statement_cache.csv` there would make otherwise valid production entries unreachable. The workflow therefore restores and saves statements under a separate key. The data cache key is `stock-screener-data-v2-<os>-<run_id>` with a `v1` fallback; the statement cache key is `stock-screener-statements-v1-<os>-<run_id>-<attempt>`. The statement cache is saved under `always()`, so a coverage-guard failure keeps the records already fetched for the next attempt. Pip is deliberately not cached: three entries of about 3 GB each (torch) evicted the price and statement caches on 29 September 2026.

`STATEMENT_FETCH_MAX_SYMBOLS_PER_RUN` is `2500` on scheduled runs, so one run can fetch a whole universe, but a cold first run may land below the 95% coverage floor (`FACTOR_MIN_STATEMENT_UNIVERSE_COVERAGE`). Scheduled production enforces that floor before scoring and publishes nothing from a partial cross-section.

**Validation mode.** A `workflow_dispatch` of the daily workflow with `mode=validation` runs the 4.x contract in isolation: it writes to `.validation-output/<run_id>`, skips the production caches, backtest writes, red-flag store and the Supabase publish, and shares no concurrency group with production. A dispatch with `mode=production` behaves like a scheduled run. The NSE and US workflows work the same way; each has its own caches and schedule, 10.5 hours apart (11:07 vs 21:37 UTC).

### 15.5 Supabase publication, scheduled jobs and private web dashboard

The production web path is downstream of the research CSV, and a set of smaller scheduled jobs fills the display tables around it.

```text
scheduled GitHub Actions (one daily workflow per market)
  -> advanced_analysis_YYYYMMDD.csv + manifest + diagnostics
  -> DashboardPublisher (service role; scheduled runs and mode=production dispatches)
  -> Supabase/Postgres read model
       screener_runs       one row per completed trading session and market
       screener_snapshot   typed query columns + complete source row in payload jsonb
       screener_history    narrow daily series retained for movers, rank history and returns
       + per-feature tables, each written by one scheduled job (below)
  -> Next.js 16 application on Vercel
       authenticated server reads under Supabase RLS
```

#### Scheduled jobs

Every job is a GitHub Actions workflow. The two that cron-job.org calls are dispatch-only; do not add a `schedule:` to them or every run doubles.

| Job | When | What it writes |
|---|---|---|
| Daily stock screener (NSE) | Four slots, 11:07-17:07 UTC, because GitHub starts scheduled jobs late. Once a session is published the rest stop at the dedupe step or the session guard. | Scores, then publishes the read model as its last step. |
| Daily US screener | 21:37 and 23:37 UTC, with retry slots at 01:37, 03:37 and 05:37 UTC because GitHub sometimes drops a run. `MARKET=US`, universe `all_listed`, annual statements from SEC EDGAR. | The same, for the US. |
| Financial statements | 03:00, 09:00, 15:00 UTC | `financial_statements` (Yahoo annual statements; EDGAR for the US); first refreshes `new_listings` (NSE only), then records `market_events`. |
| Quarterly filings | Dispatch-only; cron-job.org every 15 minutes, and daily with `full=true`. NSE. | `quarterly_filings` (one row per symbol, quarter and basis, parsed once), `shareholding_patterns`, `bulk_block_deals`, BSE-only filings (`workers/bse_filings.py`), then `market_events` and the trailing lines of `valuation_basis`. |
| Live quotes | Dispatch-only; cron-job.org every 5 minutes on weekdays. | `live_quotes` from Yahoo\'s batch endpoint, and once a day `index_members`. |
| Price series | Tuesdays and Saturdays, 22:00 UTC | Chart series in Storage under `price-series/{MARKET}/`. |
| Market breadth | 14:30 and 22:45 UTC on weekdays | `market_breadth` tables, including each stock\'s next-session levels. |
| Transcript sentiment | 04:30, 11:30, 15:30 UTC | Tone and outlook records (section 10). |
| Earnings call recordings | Every 30 minutes through the working day, plus one night run | Speech transcripts (section 10.1). |
| Red-flag shadow | 02:45 UTC | The red-flag snapshot (section 14.1). |

Nothing in this list except the filings feeding growth (section 5.4) is read by the score. Their tables are display evidence, and their schemas are in `storage/*.sql`, applied by hand.

#### Publication protocol

The publisher resolves `run_date` from the most common `Price_Bar_As_Of` in the file, then `Analysis_As_Of`, and only then the filename. This keeps renamed or replayed files from inventing a calendar date. It reports duplicate symbols and coercion drift, maps the fields needed for filtering/indexing into typed columns, and stores every original CSV field in `payload`. A new audit-only export therefore appears in drill-down without a database migration; only a field that must be filtered or indexed needs a typed-column migration. Everything is per market: `DashboardRepository` is scoped to one market at construction and `market` is part of every key.

Publication uses a recoverable reserve/write/complete protocol because PostgREST cannot wrap several chunked requests in one client transaction:

1. Refuse replacement of a completed same-date run by default. Scheduled publication passes `--if-exists skip`, which returns success and leaves the immutable snapshot unchanged. The consequence: a rescore of an already-published session is a silent no-op, and the dashboard keeps the earlier ranking (25 October 2026: a policy 5.5.0 run logged "already published; leaving its snapshot unchanged" and the site kept the 23 October ranking). Re-publishing a session needs a deliberate delete of that date first.
2. Shrink guard: refuse a run with fewer than half the previous run\'s rows, so a failed universe download cannot replace a full snapshot.
3. Date guard: if the bars are from an older session than the one the file was built for (`Expected_Price_Bar_As_Of`), raise instead of skipping as "already published".
4. Reclaim a prior zero-row reservation after cleaning orphan history and cascade-deleting partial snapshot chunks.
5. Insert a zero-row parent reservation, upsert snapshot chunks, remove stale same-date symbols, upsert slim history, and only then write the complete run metadata with a nonzero row count.
6. On a write failure, compensate by removing partial history/reservation state and fail loudly.
7. After completion, write `estimate_history`, `universe_index` and `valuation_basis`, and prune old full snapshots. A failure in any of these is logged as housekeeping and does not invalidate the already-visible new run. The publisher keeps one full snapshot per market (about 90 MB each; the free database stops writing at 500 MB); `screener_history` keeps every day and feeds Movers, rank history, the chart tail and Returns.

`latest_completed_run()` excludes zero-row reservations, so the site and schedule guard never mistake an interrupted publish for a valid run. If Supabase is unavailable, publication is the last workflow step: the CSV artifact and warmed caches already exist, and the site continues to serve the previous completed run behind its freshness warning.

#### The web application

The app is Next.js 16 on Vercel. Every page lives under `/ind` or `/us` (`/` redirects to `/ind`, and the old `/nse/...` to the same page under `/ind`); India is the NSE market and includes the BSE-only companies, shown as `SYMBOL` tagged BSE. Pages: the screener grid, the stock page, the Market page (breadth with a live point, movers by index), index pages, Movers, Watchlists, the notification bell, the Tools tab (Concalls, Results, Returns), run health, search, and CSV export. Concalls and Results are NSE only.

- **Stock page.** Four tabs: Overview, Financials, Shareholding (NSE only) and Audit. The Audit tab exposes the policy ceiling and exact gate reasons, missing fundamental/technical fields, factor coverage, and the serialized Value input sources. It treats the published row as authoritative. Technical display distinguishes `Price vs MA50` from `MA50 slope (20 sessions)`, while debt/equity is normalized from Yahoo percentage points to the human-readable ratio multiple. A listing with no published row gets the ordinary page marked "Not rated", built from `new_listings`, with a reason and a chart from the second session.
- **Not rated rows.** After the last ranked page of the India grid, a table lists `new_listings` minus the symbols the latest run rated, only when no filter other than the name search is set. They carry no score, rank or sort, and appear in neither the tiles, the universe count nor the CSV export. Search shows them tagged NEW.
- **Live prices.** Display only. The browser reads `live_quotes` after render and polls aligned to the worker\'s next run. A quote shows only when it is from a later session than the row\'s bar, and a change past `MarketProfile.max_open_gap` is withheld as a unit change, not a move. The grid\'s Price and 1D, the stock page\'s tiles and ratios (the `live_valuation` view: price over the stored basis), the Market page\'s movers and breadth, and index pages use them. Nothing scores or sorts on a live price; Stage 2 and RS rating stay on the last close.
- **Notifications.** `workers/market_events.py` writes `market_events`, one row per `(market, kind, symbol, event_key)`, from data other jobs already collect: a `results` event from the stored NSE filings (in the US, from the stored statements gaining a quarter) and a `transcript` event. The bell counts events newer than the viewer\'s `notification_reads.seen_at`, scoped to their watchlists when they have any.
- **Results, Concalls, Shareholding.** Results reads `quarterly_result_feed` as the signed-in viewer and refreshes every few minutes; Concalls reads `concall_feed` (one row per call, no text); Shareholding reads `shareholding_patterns` and `bulk_block_deals`. FII and DII are the filing\'s own institution subtotals and public is the rest.

Access is invite-only. Supabase Auth establishes the browser session; `proxy.ts` only refreshes that session, ends over-age sessions and redirects the signed-out. Membership is `requireAccess()` against `dashboard_allowlist`, and row-level security is the final data gate. The public anon key is expected in the browser; the service-role key exists only in GitHub Actions. RLS helper calls are wrapped as scalar subqueries so Postgres evaluates access once per statement rather than once per returned row.

Company logos are identifiers, not stored image blobs. The collector publishes the normalized issuer website as `logo_domain`; the browser requests the image from Brandfetch\'s CDN using the public `NEXT_PUBLIC_BRANDFETCH_CLIENT_ID`. Missing domains, absent client configuration, and CDN/image errors all fall back to the ticker initial. `workers/logo_domain_backfill.py` can still be run directly to patch missing domains. No Brandfetch secret key or company image is stored in Supabase.

## 16. Configuration defaults that materially change decisions

The first table is what scheduled production runs (Model 5.2 / policy 5.5.0). The second lists the 4.x settings, which apply to local and validation runs only. Section 20.10 lists the factor-model settings in full.

| Parameter | Production default | Decision impact |
|---|---:|---|
| `MODEL_VERSION` / `RECOMMENDATION_POLICY_VERSION` / `OUTPUT_SCHEMA_VERSION` | 5.2.0 / 5.5.0 / 4.2.0 | Set by the workflows; the runtime default is `4.0.0-candidate`. |
| `FACTOR_FUNDAMENTAL_MIN_COVERAGE_FOR_BUY` / `FACTOR_TECHNICAL_MIN_COVERAGE_FOR_BUY` | 0.70 / 0.90 | Below them prevents BUY. |
| Strong coverage floors | 0.75 fundamental / 0.90 technical | Below them prevents STRONG BUY. |
| `REQUIRE_LIQUIDITY_FOR_BUY` | true | An actionable position size is a BUY requirement. |
| `APPLY_RATING_CAP` | true | Policy gates cap the published rating (section 11.5). |
| `RANK_BY_ELIGIBILITY_CLASS` | false | Gates label and rate; they do not rank (section 12). |
| Sector relative enabled / weight / peers | true / 0.5 / 5 | Blends generic absolute points with peer percentiles (4.x scorer). |
| `TRANSCRIPT_SENTIMENT_WEIGHT` | 1.0 | Weight of the call, before the age/cycle factor. |
| `TRANSCRIPT_OUTLOOK_SHARE` / `TRANSCRIPT_OUTLOOK_ENABLED` | 0.85 / true | Outlook\'s share of the call; tone keeps the rest. Zero is tone-only, and no call waits for an outlook. |
| `TRANSCRIPT_TWO_SIDED` / `TRANSCRIPT_NEUTRAL_MIN_CALLS` | true / 30 | Call moves the score both ways around the run\'s median call; below 30 calls the centre is 50. |
| Outlook model | OpenRouter `z-ai/glm-5.3-flash` | `TRANSCRIPT_OUTLOOK_MODEL` empty reads any model\'s extraction of the current outlook version. |
| Transcript max age / half life | 180d / 90d | Current-cycle transcript eligibility and weight. |
| Transcript required for STRONG BUY | false | Optional additional high-conviction gate. |
| DCF discount/terminal growth | 11% / 4% | DCF scenario valuation (an input to the Value block). |
| `PRICE_BAR_FALLBACK_ENABLED` / `PRICE_BASIS_RESTATEMENT_ENABLED` | true (NSE) | Price-bar repair (section 5.2). |
| Target position / participation | Rs100,000 / 1% | Liquidity actionability. |
| Liquidity prefilter | false (NSE), true (US) | Where on, reduces the research universe before scoring. |

| 4.x-only parameter | Default | Decision impact |
|---|---:|---|
| Fundamental/technical blend | 70% / 30% | Core score construction. |
| `FUNDAMENTAL_MIN_COVERAGE_FOR_BUY` / `TECHNICAL_MIN_COVERAGE_FOR_BUY` | 0.55 / 0.75 | Below them prevents BUY. |
| `REQUIRE_UPTREND_FOR_BUY` | true | Requires price > MA50, nonfalling MA50, positive 3M return. |
| `STRONG_BUY_MIN_GROWTH` / `STRONG_BUY_MIN_TECH_SCORE` / `STRONG_BUY_MIN_ADX` | 0.05 / 55 / 20 | Growth, technical-score and ADX floors; `+DI > -DI` also required. |
| DCF blend weight | 0.10 | Symmetric centered DCF evidence stage (zero under Model 5). |

## 17. Failure behavior and design invariants

| Situation | Implemented behavior |
|---|---|
| No technical data collected | Daily run fails rather than ranking an empty universe. |
| One symbol misses fundamentals | Symbol remains; coverage/missing data and policy gates fail it closed. |
| Stale fundamentals used as fallback | Retained for audit but cannot receive BUY. |
| Fresh price request fails for one symbol | Reuse a valid prior cached row when available, mark it `stale_cached_fallback`, export the lag, and fail BUY conviction closed; otherwise leave the symbol unresolved. |
| Price bar lags expected session | It is never presented as aligned current evidence and cannot support BUY; only an explicit prior-cache failure fallback may remain in the row. |
| Weekend/holiday/recovery cron targets an already-published session | Skip the expensive screen and all downstream writes successfully. |
| Publisher receives an already-completed trading date | Scheduled `--if-exists skip` returns success without changing the snapshot; the CLI default refuses replacement. |
| Publisher fails after reserving a run | Remove partial history and the zero-row reservation/snapshot chunks; incomplete reservations are excluded from readers. |
| Statement-equivalent quote field is absent | Fill only from the same issuer's annual Yahoo statement when derivable and export the source; never overwrite a present quote value. |
| Factor input is structurally non-applicable | Remove its weight from that row's coverage denominator and expose `not_applicable`, distinct from `missing`. |
| Missing technical component | It reduces coverage; it does not create hidden neutral component points. |
| Empty technical evidence | Score is neutral 50, coverage zero, so BUY eligibility fails. |
| DCF unavailable / unsupported / estimated | Audit fields may exist, but the applied DCF weight is zero. |
| No transcript / prior cycle / expired transcript | Unreported: the company is untouched, with no implicit rank penalty or priority. |
| Call with no extracted outlook yet | Treated as no call until the next run reads the outlook (`Transcript_Awaiting_Outlook`). |
| High score fails a trend/coverage/quality gate | Published decision score is ceiling-capped to 59.99 or 69.99 (rank is by merit; section 12). |
| Liquidity fails | Primary rank/rating remains; actionability is false and execution rank moves it behind actionable names. |
| Red-flag feed shows severity | Shadow-only review/counterfactual; no live rating change. |

## 18. Code-level source of truth

This document describes current implementation behavior. The authoritative files for future maintenance are:

1. `app.py` — composition root and execution order.
2. `screener/runtime.py` — environment-backed defaults and feature flags.
2a. `screener/markets.py`, `screener/universe.py` — one `MarketProfile` per market, and the universe sources.
2b. `screener/statements.py`, `screener/edgar.py`, `screener/benchmark.py`, `screener/factors.py`, `screener/stage.py` — annual statement collection, benchmark/regime, factor blocks, and the display-only stage and relative-strength rating (see section 20).
3. `screener/data_collection.py` — collection, completed-bar policy, valuation alignment, liquidity metrics, and fundamentals cache; `screener/session_bars.py` and `screener/price_basis.py` — price-bar repair.
3b. `screener/quarterly_results.py`, `screener/valuation_basis.py`, `screener/expectations.py` — filing-derived growth, the stored basis of price ratios, and the display-only expectations gap.
4. `screener/market_data.py` — technical indicator algorithms and cache validation.
5. `screener/scoring/` — fundamental/technical point functions (`points.py`), coverage and specialist quality (`fundamental.py`, `sector_models.py`), technical scoring (`technical.py`), and the `StockScorer` engine (`engine.py`).
6. `screener/valuation.py` — reverse-DCF scenario and evidence contract.
7. `scoring/transcript_enricher.py`, `sentiment/*.py` (including `outlook.py` and `llm_provider.py`), `transcripts/*.py` and `workers/call_recordings.py` — transcript and outlook feature creation, eligibility, and execution overlay rank.
8. `screener/recommendation.py` — final decision mathematics, gates, ceiling rules, stability diagnostics, and primary rank implementation.
9. `screener/liquidity.py` — NSE evidence and actionability math.
10. `red_flags/*.py` — non-live risk shadow behavior.
11. `validation/reproducibility.py` — run manifest and canonical configuration hashing.
11b. `workers/scheduled_session_guard.py` — completed-session publication guard for scheduled work.
11c. `workers/dashboard_publisher.py` and `storage/dashboard_repository.py` — Supabase read-model mapping, reservation protocol, immutable-date policy, retention, and logo-domain patching.
11d. `storage/dashboard_schema.sql` and the other `storage/*.sql` files — typed/read payload schema, RLS, movers view, allowlist functions, snapshot pruning, and each feature table. They are applied by hand.
11e. `dashboard/app`, `dashboard/components`, and `dashboard/lib` — authenticated Next.js read paths, visual semantics, queries, and formatting.
11f. `workers/quarterly_filings.py`, `workers/shareholding.py`, `workers/market_events.py`, `workers/live_quotes.py`, `workers/new_listings.py`, `workers/concall_feed.py` — the feature jobs of section 15.5.
11g. `workers/logo_domain_backfill.py` — resumable Yahoo website-domain resolution for Brandfetch identifiers, run directly.
12. `tests/test_technical_scoring.py`, `tests/test_recommendation.py`, `tests/test_liquidity.py`, and `tests/test_valuation.py` — executable behavioral specifications.
13. `tests/test_statements.py`, `tests/test_benchmark.py`, `tests/test_factors.py`, `tests/test_factor_policy.py`, `tests/test_trend_risk_features.py`, `tests/test_factor_wiring.py` — executable specifications for Model 5.
14. `tests/test_markets.py`, `tests/test_valuation_basis.py` — the market-default property and the equality of the screener\'s and dashboard\'s ratio arithmetic.

## 19. Recommended interpretation workflow

For a reviewer examining an exported top-ranked row:

1. Start with `Rank`, `Investment_Rank`, `Decision_Score`, `Rating`, and `Gate_Failures` to understand the published decision.
2. Compare `Evidence_Score` with `Decision_Score` and `Decision_Score_Ceiling` to determine whether a policy cap changed the rank.
3. Inspect `Fundamental_Score`, `Technical_Score`, `Fundamental_Model`, coverage fields, component columns, and anomalies to identify core drivers.
4. Inspect `DCF_*` and `Transcript_*` contribution/eligibility columns separately; they are overlays, not substitutes for a passing core policy gate.
5. Inspect `Portfolio_Actionable`, liquidity group/impact cost, build days, and `Actionable_Rank` before treating a high research rank as executable for a target size.
6. Open **Decision audit -> Evidence coverage** for the exact missing fundamental/technical fields and each Value input's applicable/missing status and source.
7. Treat `MA50_Slope_Pct` as the change in the moving average itself; use the separately displayed `Price vs MA50` for the stock's distance from that average.
8. Inspect `Decision_Stability_Status`, margins, stale/cache/price-bar provenance, and red-flag shadow fields before interpreting a boundary result as robust.
9. Use the adjacent manifest and diagnostics file to reproduce the exact configuration, code state, source universe, and cached inputs.

---

## 20. Model 5 factor architecture (scheduled production)

**Status:** scheduled production, and any dispatch with `mode=production`, runs model `5.2.0`, recommendation policy `5.5.0` and additive output schema `4.2.0` in both markets. Other runs keep `4.0.0-candidate`. The model number moves with a semantic change to the ranking (5.1: value/quality reweighting and research-first ranking; 5.2: the latest quarter in the growth block and the 0.25/0.25/0.15/0.30/0.05 weights); the policy number moves with the gates and the evidence blend (5.2: momentum percentile floors off; 5.3: tolerance band on the MA50 test; 5.4: a risk-off market no longer disables STRONG BUY; 5.5: a call waits for its outlook and the published score is one run percentile). `docs/model_methodology.md` records the reasoning and evidence for each change. Section 20.9 says what has and has not been validated.

### 20.1 Why the 4.x core score was replaced

Three defects motivated the redesign, all visible in sections 7 and 8 above:

1. **The 70% fundamental block merges incompatible concepts.** Value, profitability,
   balance-sheet strength, growth and accounting stability are summed into one number, so a
   cheap multiple can offset poor returns on capital with no trace in the output.
2. **The 30% technical block double-counts one price path.** MA20, MA50, MACD, RSI, StochRSI,
   Bollinger position, one-month momentum, ADX and CMF are largely different descriptions of
   the same recent move. Section 8.2's own comment notes that four components already spend 40
   of 132 points penalising an extended chart.
3. **Medium-term cross-sectional momentum is absent.** The technical block measures 20-to-65
   sessions. Momentum research is centred on 3-to-12-month formation windows, which the
   previous six-month download could not even express.

Model 5 keeps the idea of separating accounting evidence from market evidence, but
makes each block economically separable.

### 20.2 Blocks and weights

```text
Research_Score_Raw = 0.25 * Quality
                   + 0.25 * Growth
                   + 0.15 * Value
                   + 0.30 * Momentum
                   + 0.05 * Risk
```

Every block is a **coverage-shrunk weighted percentile composite** of its own inputs:

```text
block_percentile = sum(w_i * percentile_i) / sum(w_i over observed i)
coverage         = sum(w_i over observed i) / sum(w_i over applicable i)
Block_Score      = clamp(50 + coverage * (block_percentile - 50), 0, 100)
```

This mirrors the shrinkage the 4.x scorer already applies. A missing but applicable input stays
in the coverage denominator and lowers confidence; a structurally non-applicable input leaves
the denominator entirely. Neither condition is treated as the worst observed economic value.

Percentiles use the symmetric `(rank - 1) / (n - 1)` transform, not the pandas `rank(pct=True)`
convention, which maps onto `[1/n, 1]` and would deny the best observation full credit while
biasing every inverted (lower-is-better) metric.

| Block | Weight | Inputs (weight, direction) |
|---|---:|---|
| Quality (generic) | 0.25 | ROIC .20 up, gross profit/assets .15 up, OCF/assets .13 up, FCF/assets .09 up, accruals/assets .10 down, interest coverage .05 up, net debt/EBITDA .05 down, operating-margin stability .08 down, earnings stability .08 down, asset growth .04 down, 3Y dilution .03 down |
| Quality (financial) | 0.25 | ROE .28 up, ROA .22 up, equity/assets .20 up, earnings stability .15 down, profit margin .15 up |
| Growth | 0.25 | 65% of the block: revenue CAGR 3Y .25 up, EPS CAGR 3Y .20 up, revenue acceleration .15 up, EPS acceleration .15 up, margin direction .15 up, cash conversion .10 up (shares of those six). 35% of the block (`FACTOR_GROWTH_QUARTER_SHARE`): latest-quarter earnings growth .20 up and revenue growth .15 up, against the same quarter a year earlier |
| Value | 0.15 | Earnings yield .25 up, FCF yield .25 up, EBIT/EV .20 up, book yield .15 up, reverse-DCF score .15 up |
| Momentum | 0.30 | Risk-adjusted 12-1 .30 up, risk-adjusted 6-1 .25 up, 6M sector-relative .20 up, 6M market-relative .15 up, signed trend quality .10 up |
| Risk | 0.05 | Annualised volatility .25 down, max 1Y drawdown .20 up, trading frequency .20 up, downside deviation .15 down, gap risk .10 down, return concentration .10 down |

Notes on specific inputs:

- **The latest quarter.** Every annual input is a year or more old, so a company whose business turned two quarters ago is still scored on the year before it turned. The two quarterly growth inputs are the only growth evidence that moves between annual filings. On NSE they are measured from stored results filings (section 5.4), and an earnings figure the source cannot compute (a loss in the base quarter) is missing for that row and costs it coverage. `FACTOR_GROWTH_QUARTER_SHARE=0` restores the annual-only block.
- **Two quality templates.** Banks, NBFCs, insurers and capital-markets firms report no EBIT,
  gross profit or current assets, and Yahoo omits operating cash flow for most of them. Scoring
  them on the industrial-company template would mark them down for *absent* data rather than
  *different* data, so financial rows are ranked against each other on what their statements
  actually report. Measured coverage on the financial template is 1.00.
- **Book yield is sector-gated.** Offered only for Financial Services, Real Estate and
  Utilities. Elsewhere it rewards accounting history rather than economics, so it is simply not
  an input and drops out of the coverage denominator.
- **DCF applicability follows evidence eligibility.** A neutral audit-only reverse DCF that did
  not meet `DCF_Blend_Eligible` is not counted as observed Value coverage. If eligible, its weight
  enters the denominator and a missing score is a real coverage gap.
- **Value input audit.** `Value_Input_Audit` serializes each input's weight, `available`,
  `missing`, or `not_applicable` status, source, and reason into the CSV/payload. This is the
  source of the stock page's Value evidence table; it is not reconstructed in the browser.
- **Signed trend quality.** `Trend_Quality_R2` is the R-squared of log price against time
  carrying the sign of the slope, on `[-1, 1]`. An unsigned R-squared scores a smooth,
  relentless decline a perfect 1.0 — the best possible reading in a block where higher is better.
- **No guidance input.** The proposal asked for forward/management-guidance evidence. No
  point-in-time consensus feed is wired in and approximating one would be a look-ahead hazard,
  so the substitute is cash conversion, which the same proposal requires as confirmation for
  high reported earnings growth.
- **DCF is not double-counted.** Reverse-DCF evidence is a Value input, so `DCF_Blend_Weight` is
  set to `0.0` and the finalizer's separate centered DCF stage becomes a no-op. The DCF audit
  columns are untouched.

### 20.3 The published score is a percentile — and why

`Research_Score_Raw` is re-ranked cross-sectionally before publication:

```text
Research_Score = percentile(Research_Score_Raw)   # FACTOR_SCORE_AS_PERCENTILE, default True
Combined_Score = Core_Score = Research_Score
```

Each block is already roughly uniform on `[0, 100]`, so averaging five of them is a diversifying
operation and the composite collapses toward 50. Measured on a 39-name large-cap run: block
standard deviations were 14-23, the raw blend's was **9.95**. Against the 70/60/50/40 rating
bands — which were calibrated for the 4.x *absolute* score — exactly **one** name of 39 cleared
70 and **none** was rated BUY. Ranking the blend restores the bands' meaning: `>= 70` is the top
30% of the cross-section, `>= 60` the top 40%.

**This makes Model 5 ratings explicitly relative,** which is a genuine semantic change from
4.x and has two consequences that remain part of the production contract:

- In any universe, roughly 40% of rows score below 50 and are labelled REDUCE or SELL. On a
  40-name blue-chip watchlist that reads as absurdly bearish; on a full-NSE run it is closer to
  the intended meaning. **Model 5 is designed for full-universe runs.**
- "Top 30% of a collapsing market" would otherwise be published as STRONG BUY. What prevents
  that is not the score but the *absolute* protections: the market-regime overlay (20.6) and the
  hard trend, quality, coverage and liquidity gates (20.5), all of which fail closed.

The published `Evidence_Score` is a second percentile: of the research score plus the DCF and earnings-call adjustments across the run (section 11.1). `Research_Score`, the block scores and the block percentiles do not include the call.

Set `FACTOR_SCORE_AS_PERCENTILE=False` to publish the raw blend instead; the rating bands then
need recalibrating, and `Evidence_Score` is clipped at 100 instead of ranked.

### 20.4 New data inputs

| Input | Source | Availability on a 30-name NSE sample |
|---|---|---|
| Total assets, invested capital, equity, total debt, shares | `Ticker.balance_sheet` | 100% |
| Total revenue, net income, interest expense, tax rate, diluted EPS | `Ticker.income_stmt` | 100% |
| Free cash flow, capital expenditure | `Ticker.cashflow` | 100% |
| Operating cash flow | `Ticker.cashflow` | 93% |
| EBIT | `Ticker.income_stmt` | 80% (absent for financials) |
| Gross profit, current assets/liabilities | `Ticker.income_stmt` / `balance_sheet` | 73% (absent for financials) |
| 4-5 years of annual history (3Y CAGR needs 4) | all three statements | 100% |
| Benchmark index (NSE: `^CRSLDX`, fallback `^NSEI`; the US profile names its own) | `yf.download` | available, ~493 sessions |
| Latest-quarter revenue and earnings growth | NSE results filings (`quarterly_filings`); Yahoo for the rest | NSE companies with a filing |

Yahoo's quote metadata supplies **none** of these: it has no total assets, no EBIT, no gross
profit, no cash-flow history and no multi-year series, and it omits `returnOnEquity` and
`returnOnAssets` outright for part of the universe (RELIANCE and HDFCBANK both returned `None`
in the audit).

**Collection cost.** A cold full-NSE screen is dominated by the fundamental fetch (about an hour for 2,300 symbols), not by statements. Statements restate quarterly at most, so `STATEMENT_CACHE_MAX_AGE_DAYS` defaults to 90 and `STATEMENT_FETCH_MAX_SYMBOLS_PER_RUN` bounds each run\'s backfill (2,500 on scheduled runs, 400 on a validation dispatch). Symbols not yet backfilled report no statement evidence and fail closed, and a scheduled run refuses to score below 95% usable statement coverage. Statements are deliberately not a sixth path in the production market-data cache composite (section 15.4).

### 20.5 Gates

Model 5 keeps every shared data-integrity gate from section 11.3 (core score present, price
bar aligned, stale fundamentals, `Data_Quality != LOW`, specialist model required, two or more
anomalies) and replaces the trend and high-conviction gates.

**BUY** (any failure sets the ceiling to `59.99`):

| Gate | Threshold |
|---|---|
| Price vs MA200 | `Technical_Price >= 0.98 * MA200` |
| MA200 slope | `>= 0` |
| Confirmed breakdown | fails if below MA200 for 10+ sessions **and** MA200 falling **and** 6M relative strength negative |
| 6M market relative strength | `> 0` |
| 6M sector relative strength | `> 0` **when observed**; absence is never a failure |
| Quality percentile | `>= 40` |
| Factor block coverage | every block at or above `FACTOR_MIN_BLOCK_COVERAGE` (0.50) |
| Fundamental coverage | `>= 0.70` (up from 0.55) |
| Technical coverage | `>= 0.90` (up from 0.75) |
| Execution liquidity | `Portfolio_Actionable` (`REQUIRE_LIQUIDITY_FOR_BUY`) |

**STRONG BUY** (inherits every BUY failure; further failures cap at `69.99`; the coverage, specialised-quality, anomaly and negative-FCF conditions of section 11.4 also apply):

| Gate | Threshold |
|---|---|
| Quality / Growth percentile | `>= 70` / `>= 60` (the momentum percentile floor of 70 was switched off in policy 5.2.0: a percentile floor is cross-sectional, so it keeps clearing in a falling market and buys no absolute protection) |
| Moving-average stack | `Technical_Price >= 0.98 * MA50` and `MA50 > MA200` (the 2% band on the MA50 test since policy 5.3.0; the order of the averages stays strict) |
| MA200 slope | strictly `> 0` |
| 12M market relative strength | `> 0` |

**Hysteresis.** The 2% tolerance band is deliberate: an exact boundary makes a stock oscillating
around its average flip its published rating daily. Entry requires `price >= 0.98 * MA200`; the
stricter *confirmed breakdown* condition requires persistence, a falling average and weak
relative strength together, so a single dip through the line cannot revoke a rating that a
rebound would restore.

**Liquidity is now a BUY requirement, not only an execution overlay.** An illiquid name can be
excellent research and still unsuitable as a published BUY. The research view is preserved
separately (20.7), so nothing is lost.

### 20.6 Market-regime overlay

`BenchmarkProvider` classifies the broad market from the benchmark's 200-session average:

```text
RISK_ON  : index > MA200 by more than the neutral band AND MA200 slope > 0
RISK_OFF : index < MA200 by more than the neutral band AND MA200 slope < 0
NEUTRAL  : inside the band, or level and trend disagree
UNKNOWN  : fewer than MA + slope sessions of index history
```

| Regime | Effect |
|---|---|
| RISK_ON | normal policy |
| NEUTRAL | normal policy (the momentum floor of 85 was switched off in policy 5.2.0 with the one in 20.5) |
| RISK_OFF | BUY additionally requires momentum percentile `>= 90`. STRONG BUY is not disabled (policy 5.4.0, `REGIME_RISK_OFF_DISABLES_STRONG_BUY=false`): a stock that clears every gate of its own used to read BUY for as long as the index stayed down, and its own MA200, breakdown, MA50/MA200 stack and relative-strength gates already bar a stock that is falling with the market |

The overlay changes **deployment conviction only**. It never edits a factor score, so the
research ranking stays fully visible and auditable in every regime. This is locked by
`test_regime_never_edits_the_research_score`.

### 20.7 Separated decision views and ranking

Collapsing every gate failure onto an identical `59.99` creates a large artificial cluster and
destroys the ordering *within* it — ranking that cluster by `Decision_Score` sorts a column that
is constant by construction and falls through to the symbol tie-break, i.e. **alphabetical order
presented as investment merit**. Model 5 publishes separate views instead:

| Field | Meaning |
|---|---|
| `Research_Rating` | Uncapped research view (band of `Evidence_Score`) |
| `Policy_Eligible_Rating` | The gate-capped label; equals `Rating` while `APPLY_RATING_CAP` is true |
| `Execution_Status` | `ACTIONABLE` / `NOT_ACTIONABLE` |
| `Primary_Gate` | Most severe binding reason, as a stable slug (`BELOW_MA200`, `LOW_QUALITY`, `ILLIQUID`, ...) |
| `Gate_Severity` | Count of simultaneous failures |
| `Eligibility_Class` | `0` clears every gate, `1` BUY-eligible, `2` policy-capped, `3` unscorable |

`Primary_Gate` answers "what is stopping this row from being rated higher", so a BUY-eligible row
can still report a STRONG BUY gate. Patterns are scanned in severity order, not in the order the
failures happened to be appended.

The primary rank does **not** sort by `Eligibility_Class` (`RANK_BY_ELIGIBILITY_CLASS=false` since Model 5.1; section 12). The point-in-time validation found that ranking eligibility first cost 5-16 CAGR points wherever the gates bound and changed nothing in the 2018-2020 drawdown. The gates still compute and publish in full, so a failing name is labelled rather than hidden, but they are no longer a stock-selection input. With the flag set to true:

```text
Investment_Rank = sort(Eligibility_Class ASC, Evidence_Score DESC, Research_Score DESC,
                       Gate_Severity ASC, Symbol ASC)
```

`Decision_Score`, `Final_Score` and the ceiling logic are unchanged either way, so every existing consumer keeps working.

### 20.8 Known gap: financial-sector regulatory evidence

`Gross_NPA`, `Net_NPA`, `Capital_Adequacy` and `Solvency_Ratio` are declared as required
specialist evidence (section 7.6) and are required by `specialized_quality_gate`, but **no
collector in this repository has ever populated them** and Yahoo does not publish them. The
practical effect, in 4.x as well as 5.0, is that **every bank, NBFC and insurer is permanently
barred from BUY** — silently removing the largest sector of the Indian market from the actionable
universe. This was confirmed on a live run: all 9 financial rows failed with
`missing specialized quality data`.

Model 5's financial quality template scores these companies correctly from statement evidence
at full coverage (measured spread on the same run: HDFCLIFE 5.1 to BAJFINANCE 100.0), so the gate
is now the only thing blocking them.

`FACTOR_FINANCIAL_STATEMENT_QUALITY_SUFFICIENT` (default **False**) accepts the statement
template as sufficient for BUY and keeps the regulatory requirement for STRONG BUY only. It
defaults to the existing fail-closed behaviour because this is a risk-policy decision, not a
technical one.

**That flag is necessary but not sufficient for banks and NBFCs.** The same never-collected
fields also sit in the *denominator* of `Fundamental_Coverage` (section 7.6), which permanently
caps them:

| Model | Expected fields | Always missing | Ceiling on `Fundamental_Coverage` |
|---|---:|---|---:|
| Bank / NBFC Equity Quality | 8 | Gross_NPA, Net_NPA, Capital_Adequacy | **0.625** |
| Insurance Equity Quality | 6 | Solvency_Ratio | **0.833** |

Model 5's BUY floor is 0.70, so **banks and NBFCs fail on coverage even with the flag set**;
insurers clear BUY but can never reach the 0.75 STRONG BUY floor. Under 4.x the 0.55 BUY floor is
cleared, so there the specialist gate alone is the binding constraint.

Fully closing the gap therefore needs one of:

1. an NPA/CAR/solvency feed from exchange filings — the correct fix, and the only one that makes
   the evidence real rather than merely uncounted; or
2. removing structurally uncollectable fields from the coverage denominator, so coverage measures
   *how much of what is knowable is known*. This changes 4.x behaviour too and should be a
   separate, reviewed change rather than a side effect of the Model 5 rollout.

**Closing the gap needs a feed.** `docs/financial_regulatory_data_feed_scope.md` records the verified route: NSE\'s `corporates-financial-results` API serves bank filings under a `BANKING_` XBRL taxonomy carrying `PercentageOfGrossNpa` and `PercentageOfNpa`. The consolidated filing returns `0.00` for every NPA tag, so a naive reader would publish pristine asset quality for every bank; the scope document makes that a required test. NBFC asset quality and capital adequacy are only in the results PDF, which needs coordinate-based table extraction because labels and values are separated in the text stream. No scorer reads either feed yet: the NPA, capital-adequacy and solvency fields are still never populated, and the alternative of removing uncollectable fields from the coverage denominator would change 4.x behaviour and should be a separate, reviewed change.

### 20.9 Validation status and evidence

Predictive evidence comes from the point-in-time backtest in `backtest/` (section 15.3), run with `python -m tools.run_p0_backtest`. A signal forms on the close of day t and fills at the next session\'s open; returns are adjusted for corporate actions and net of costs; delisted securities stay in. The weights and gates of Models 5.1 and 5.2 were chosen on its windows (the declared grids are in `backtest/strategies.py`: the gate grid, `GROWTH_REWEIGHT_GRID` and `VALUE_WEIGHT_GRID`, which led to cutting value from 0.25 to 0.15). Results and the commands that reproduce them are in the README\'s "Point-in-time validation" section, and the protocol is in `docs/model_methodology.md`; they are not copied here because they change with each run.

What that evidence does not show:

- The weights were fitted on the same windows (in-sample). **Forward validation is pending**, and the exported `Model_Validation_Status` says so: "Production active; point-in-time validated over four windows incl. 2018-2020 drawdown; weights fitted in-sample, forward validation pending" on NSE. The US export says validation was done on NSE data only.
- Windows after early 2025 use vendor statements as restated today, dated at the filing deadline (`reports_advanced/backtest_ext`): conservative on timing, but not the figures as first filed.
- The backtest ranks `Research_Score` and has no calls, so the earnings-call evidence has its own, shorter studies (`docs/model_methodology.md`).
- `screener/statements.py` derives from the statements the vendor publishes today. For a live screen that is correct; it does not reconstruct what was knowable on a past date.

A scheduled run fails before scoring when usable statements cover less than 95% of the universe (`FACTOR_MIN_STATEMENT_UNIVERSE_COVERAGE`), so a partial backfill cannot be mistaken for a full-universe result.

### 20.10 Model 5 configuration reference

| Parameter | Runtime default / scheduled override | Effect |
|---|---:|---|
| `FACTOR_MODEL_ENABLED` | false / true | Master switch; the workflows enable it for scheduled runs and `mode=production` dispatches, and leave it false for `mode=validation` |
| `MODEL_VERSION` / `RECOMMENDATION_POLICY_VERSION` / `OUTPUT_SCHEMA_VERSION` | local model/policy `4.0.0-candidate`; scheduled model/policy `5.2.0` / `5.5.0`; schema `4.2.0` | Scheduled model, policy, and additive export contracts are versioned independently |
| `FACTOR_WEIGHT_{QUALITY,GROWTH,VALUE,MOMENTUM,RISK}` | .25/.25/.15/.30/.05 | Block blend (5.1 and 5.2 moved ten points each; set .20/.25/.25 growth/value/momentum to restore 5.1) |
| `FACTOR_GROWTH_QUARTER_SHARE` | 0.35 | Share of the growth block carried by the latest quarter |
| `FACTOR_SCORE_AS_PERCENTILE` | true | Publish the blend as a cross-sectional percentile |
| `FACTOR_SECTOR_NEUTRAL` / `FACTOR_MIN_SECTOR_PEERS` | true / 8 | Rank inside sector when it is large enough |
| `FACTOR_MIN_BLOCK_COVERAGE` | 0.50 | Block coverage floor for BUY |
| `FACTOR_VALUE_QUALITY_FLOOR_PCT` / `FACTOR_VALUE_CEILING_WHEN_LOW_QUALITY` | 30 / 50 | Value-trap cap |
| History/cache contract / `LEGACY_HISTORY_WINDOW_SESSIONS` | 4.x: 6mo/v6; Model 5: 2y/v7; 126 | Model-selected download depth and cache schema; six-month feature pinning applies to the longer Model 5 frame |
| `BENCHMARK_INDEX_SYMBOL` / `BENCHMARK_INDEX_FALLBACK` | ^CRSLDX / ^NSEI | Relative strength and regime source |
| `MARKET_REGIME_ENABLED` / `MARKET_REGIME_MA_SESSIONS` / `MARKET_REGIME_NEUTRAL_BAND_PCT` | true / 200 / 2.0 | Regime classification |
| `REQUIRE_MA200_TREND_FOR_BUY` / `BUY_MA200_TOLERANCE` | true / 0.98 | Trend gate and hysteresis band |
| `BREAKDOWN_CONFIRM_SESSIONS` | 10 | Confirmed-breakdown persistence |
| `BUY_MIN_QUALITY_PCT` / `STRONG_BUY_MIN_{QUALITY,GROWTH}_PCT` | 40 / 70, 60 | Factor percentile floors |
| `FACTOR_FUNDAMENTAL_MIN_COVERAGE_FOR_BUY` / `FACTOR_TECHNICAL_MIN_COVERAGE_FOR_BUY` | 0.70 / 0.90 | Tightened BUY coverage |
| `REQUIRE_LIQUIDITY_FOR_BUY` | true | Execution liquidity as a BUY gate |
| `RANK_BY_ELIGIBILITY_CLASS` | false | Eligibility-first primary ranking when true (off since 5.1) |
| `APPLY_RATING_CAP` | true | Policy gates cap the published rating; false caps on evidence-quality gates only |
| `REGIME_RISK_OFF_DISABLES_STRONG_BUY` | false | Policy 5.4.0 |
| `STRONG_BUY_MIN_MOMENTUM_PCT` / `REGIME_NEUTRAL_MIN_MOMENTUM_PCT_FOR_STRONG_BUY` | 0 / 0 | Momentum percentile floors, off since policy 5.2.0 |
| `STRONG_BUY_MA50_TOLERANCE` | 0.98 | Price may sit 2% under its MA50 and still count as stacked (policy 5.3.0) |
| `FACTOR_FINANCIAL_STATEMENT_QUALITY_SUFFICIENT` | false | See 20.8 — risk-policy decision |
| `FACTOR_MIN_STATEMENT_UNIVERSE_COVERAGE` | 0.95 | Scheduled production fails before scoring and side effects if usable statement evidence covers less than 95% of the research universe |
| `TRANSCRIPT_SENTIMENT_WEIGHT` / `TRANSCRIPT_OUTLOOK_SHARE` / `TRANSCRIPT_TWO_SIDED` | 1.0 / 0.85 / true | Earnings-call evidence (sections 10 and 11.1) |
| `STATEMENT_CACHE_MAX_AGE_DAYS` / `STATEMENT_FETCH_MAX_SYMBOLS_PER_RUN` | 90 / 2,500 scheduled (400 validation dispatch) | Statement cache TTL and recovery budget |
