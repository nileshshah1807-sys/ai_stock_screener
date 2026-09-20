# AI Stock Screener — As-Built System Architecture Design

- **Status:** implementation-derived design document
- **Scope:** current `app.run_daily_analysis()` production path and its supporting modules
- **Scheduled production contract:** model `5.0.0` / recommendation policy `5.0.0` / output schema `4.2.0`
- **Local and manual-daily default:** `4.0.0-candidate`, with the factor switch off
- **Last reviewed against code:** 2026-08-19 (`main` through PR #12, plus workflow retirement and repository cleanup)
- **Live workflows:** `daily-stock-screener.yml`, `red-flag-shadow.yml`, `transcript-sentiment.yml` (see `development_guidelines.md`)

> **Two models live in this codebase.** Sections 1-19 describe the shared pipeline and the
> legacy **4.x model**, which remains the local/runtime default (`FACTOR_MODEL_ENABLED=False`)
> and the isolated manual-daily path. Section 20 describes the **Model 5.0 factor
> architecture**, which replaces the 70/30 core score with five separable
> factor blocks, MA200 trend gates, a market-regime overlay and eligibility-class ranking.
> Scheduled production selects Model 5.0 explicitly in GitHub Actions. Its operational
> promotion does not resolve the still-pending point-in-time, out-of-sample predictive
> validation. Where Model 5.0 changes a rule in sections 1-19, section 20 says so explicitly.

> **Research-model boundary.** This application produces deterministic research ranks and heuristic rating labels. `Rating`, `Decision_Score`, and `Final_Score` are not forecasts of return, fair value, or probability of profit. The configured `Model_Validation_Status` explicitly says point-in-time, out-of-sample validation is pending. The system's purpose is to make the screening logic auditable, reproducible, and reviewable—not to make an unvalidated investment-performance claim.

## 1. Executive summary

The application is an NSE equity research screener. It creates one row per successfully collected market-data symbol, derives a core score from fundamentals and technicals, applies independent DCF and transcript evidence, then applies hard policy gates before it ranks the result set. The primary rank is **not** a simple sort of raw score: it is ordered by the post-gate `Decision_Score` first, then uncapped evidence, then ticker symbol.

The main design principles implemented in the code are:

1. **Research universe first, execution overlay later.** The default full-NSE run retains the broad successfully collected universe; liquidity normally affects `Actionable_Rank`, not `Rating`, `Final_Score`, or primary `Rank`.
2. **Completed-bar consistency.** Each price-sensitive technical feature uses the same completed NSE daily bar. Raw `Current_Price` is retained for traded-value/valuation display; adjusted `Technical_Price` is used for returns, indicators, and chart gates.
3. **Score/evidence/policy separation.** Scoring, DCF, transcripts, liquidity, and red flags are evidence producers. Only `RecommendationPolicy` publishes canonical score, rating, eligibility, gate, and rank fields.
4. **Fail-closed high conviction.** Missing coverage, stale fundamentals, invalid specialist-model evidence, multiple data anomalies, and weak trend structure cap a candidate below BUY or STRONG BUY even if its raw score is high.
5. **Deterministic audit trail.** Stable sort order, decimal half-up rounding, collection diagnostics, output manifests, configuration hashing, and per-symbol gate reasons are exported.
6. **Immutable completed-session publication.** Scheduled work is keyed to the expected completed NSE trading session, not the calendar day. An already-published session is reused on weekends, holidays, and recovery cron attempts instead of being rescored against revised vendor metadata.
7. **Wide write model, narrow read model.** The CSV remains the complete research contract. Supabase stores indexed dashboard fields plus the entire source row in `payload`, while the authenticated Next.js application reads only the projections each surface needs.

## 2. Architecture overview

```text
                                  External sources
          ┌──────────────────────────────────────────────────────────────┐
          │ NSE equity master / monthly liquidity category & impact cost │
          │ Yahoo Finance: 4.x 6mo/v6; Model 5.0 2y/v7 + fundamentals   │
          │ Supabase: transcript/red flags + dashboard read model        │
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
│    generic or specialist fundamentals (0-100) + technicals (0-100)                 │
│    Core_Score = 0.70 * Fundamental_Score + 0.30 * Technical_Score                  │
│    exports coverage, anomalies, component points, provisional core diagnostics     │
└───────────────────────────────────────────────────────────────────────────────────┘
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
┌──────────────────────────────────────┐  ┌───────────────────────────────────────┐
│ 3a. Reverse DCF evidence             │  │ 3b. Transcript evidence                │
│ Base-case value / market-cap -> score │  │ Current-cycle cached call only         │
│ reported positive FCF only for blend  │  │ age/cycle weighting; downside-only     │
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
| Composition root | `app.py::run_daily_analysis` | Orders the daily job, handles output/reporting, assigns run provenance. | Indirectly, by calling finalizer once. |
| Runtime configuration | `screener/runtime.py::Config` | Environment-backed defaults; optionally overridden by `config_local.py`. | Policy parameters only. |
| Collection | `screener/data_collection.py::StockDataCollector` | NSE universe, model-specific Yahoo OHLCV (4.x `6mo`/v6; Model 5.0 `2y`/v7), cache reuse, Yahoo fundamentals, collection diagnostics. | No. |
| Technical calculation | `screener/market_data.py::TechnicalEnhancer` | RSI, ADX/+DI/-DI, StochRSI, ATR, returns. | No. |
| Liquidity source | `screener/liquidity.py::NSELiquidityProvider` | Joins NSE monthly Group I/II/III and Rs1 lakh mean impact cost. | No. |
| Annual statements | `screener/statements.py::FinancialStatementCollector` | Caches annual Yahoo statements, derives factor inputs, and safely fills missing quote metadata with source markers. | No. |
| Core model | `screener/scoring.py::StockScorer` | Fundamental/technical component scores, sector-relative comparison, coverage, specialist quality checks. | Exports only provisional `Core_*` diagnostics. |
| Valuation evidence | `screener/valuation.py::ReverseDCFModel` | Reverse-DCF diagnostics and blend-eligible valuation score. | No. |
| Transcript evidence | `scoring/transcript_enricher.py::TranscriptSentimentEnricher` | Loads cached sentiments and establishes recency/cycle eligibility. | No. |
| Decision policy | `screener/recommendation.py::RecommendationPolicy` | Evidence blend, policy gates, ceilings, ratings, stability diagnostics, primary ranks. | **Yes; sole authority.** |
| Execution overlay | `LiquidityQualityEnricher` and `rank_actionable_recommendations` | Position-size actionability and `Actionable_Rank`. | No. |
| Risk shadow layer | `red_flags/enricher.py`, `red_flags/shadow.py` | Cached red flags and counterfactual outcomes if confirmed. | No. |
| Outputs | `screener/reporting.py`, `validation/reproducibility.py` | Dashboard/report delivery, CSV, provenance manifest and hashes. | No. |
| Schedule guard | `workers/scheduled_session_guard.py` | Compares the expected completed NSE session with the latest completed Supabase run before expensive scheduled work. | No. |
| Dashboard publisher | `workers/dashboard_publisher.py`, `storage/dashboard_repository.py` | Maps the CSV into run, snapshot, and slim-history tables using a reserve/write/complete protocol. | No; publishes existing decisions. |
| Web read model | `dashboard/` | Authenticated Vercel/Next.js screener, movers, health, stock drill-down, decision audit, and logo rendering. | No; read-only for research data. |

## 4. End-to-end run sequence

`app.run_daily_analysis()` executes the following order. This order matters because later evidence is allowed to modify evidence score but not bypass gates.

1. Instantiate `Config`, determine `analysis_now` in `Asia/Kolkata` by default, and initialize cache folders.
2. Build the universe through `StockDataCollector.get_comprehensive_stock_list()`.
3. Download/reuse the model-specific OHLCV window (`6mo` for the default 4.x path, `2y` for Model 5.0); retain only symbols with a valid completed and aligned daily bar and enough usable history.
4. Join NSE liquidity categories and impact-cost evidence once for the collected symbols.
5. Apply the liquidity prefilter only when all of these are true: `LIQUIDITY_FILTER_ENABLED`, `SCAN_ALL_NSE`, and `PREFILTER_RESEARCH_UNIVERSE_BY_LIQUIDITY`. The default is **not** to prefilter.
6. Fetch or reuse fundamentals and left-join them to the technical universe. A fundamental miss does not delete a technically collected symbol; it becomes missing/limited evidence and is later prevented from receiving BUY conviction.
7. Recalculate price-dependent valuation ratios using the same completed close used for price technicals.
8. When Model 5.0 is enabled, fetch/reuse annual statements, fill only absent quote fields from statement-derived equivalents, record a per-field source, and rerun completed-close valuation alignment. Enforce the run-wide statement-coverage floor before scoring.
9. Run `StockScorer.score_all_stocks()` to create the 4.x core diagnostics, including exact missing fundamental and technical fields.
10. If enabled, run `ReverseDCFModel.enrich()`.
11. If enabled, load precomputed transcript evidence. A transcript failure is fatal by default (`TRANSCRIPT_FAIL_ON_ERROR=True`), but can be configured to log and skip.
12. When Model 5.0 is selected, load benchmark context and run the factor model to create its block scores, applicability-aware coverage, per-input Value audit, and research score.
13. Attach liquidity/actionability evidence before policy finalization so Model 5.0 can enforce its BUY liquidity gate without letting execution capacity prefilter the research universe.
14. Run `finalize_recommendations()`: the sole writer of canonical decision fields and primary research ranks.
15. Optionally attach red-flag records and generate a shadow-only counterfactual, then generate `Actionable_Rank` without changing the primary investment ordering.
16. Add model/config/run provenance, fetch display-only news sentiment for the already-ranked top N rows, write CSV/manifest/diagnostics/dashboard, and optionally send reports.
17. Optionally append the result to a model-version-separated backtest history.

The scheduled GitHub workflow wraps this in an outer publication protocol:

1. A same-UTC-day success check suppresses the 18:30 IST recovery attempt when the 16:30 IST run already succeeded.
2. `scheduled_session_guard` suppresses weekend, configured-holiday, and already-published completed-session rebuilds even when no workflow succeeded on the current calendar day.
3. The report artifact and both cache namespaces are saved before dashboard publication.
4. `dashboard_publisher --if-exists skip` treats a race or replay of an already-published trading date as a successful no-op.
5. Only a completed scheduled run updates the Supabase read model; manual dispatches remain isolated validation runs.

## 5. Research universe, data contracts, and collection controls

### 5.1 Universe selection

- In full-scan mode (`SCAN_ALL_NSE=True`), the collector retrieves NSE's `EQUITY_L.csv`, adds a fixed liquid-name safety list, normalizes symbols, and sorts them.
- If the master file fails, the built-in safety list remains available.
- In watchlist mode (`SCAN_ALL_NSE=False`), the configured `CUSTOM_WATCHLIST` replaces the full universe.
- Collection diagnostics persist the selected, requested, collected, failed, and missing symbols. This prevents a different network-collected cross-section from appearing reproducible merely because code/config were unchanged.

### 5.2 Completed market-bar policy

The history contract is selected with the model. With `FACTOR_MODEL_ENABLED=false`, the
default 4.x path retains its established `6mo` download and technical-cache contract v6.
Enabling Model 5.0 selects `2y` and technical-cache contract v7 because its 200-day average,
12-1 momentum formation window and one-year drawdown cannot be expressed in six months.
The distinct cache versions prevent either model from accepting incompatible technical rows.

The longer Model 5.0 window does **not** redefine features that are *defined* on a six-month
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

- Default time zone: `Asia/Kolkata`.
- Daily session completion cutoff: `16:15` IST.
- Before the cutoff, today's bar is excluded unless the explicit `ALLOW_PROVISIONAL_MARKET_BARS` escape hatch is enabled.
- After the cutoff, a normal NSE session needs today's complete bar; weekends and configured NSE holidays use the prior expected session.
- A fresh provider row is admitted only when its provenance is valid. If the provider fails for one symbol, a schema-valid prior cached row may be retained as `stale_cached_fallback`; it carries its real session lag, is never described as current, and cannot support BUY conviction.
- A symbol with neither fresh evidence nor a usable prior row is unresolved and excluded. Diagnostics distinguish provider failures, stale fallbacks, and unresolved symbols instead of reporting all three as one failure class.
- Completed daily bars are immutable. Cache validity is therefore keyed primarily to the recorded expected exchange session, schema, indicator version, completion state, and provenance rather than expiring a Friday snapshot merely because wall-clock hours passed over a weekend.

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

A ratio is recomputed only if all needed denominators are valid (and nonzero where required); otherwise the fetched value remains for audit. `*_Price_Aligned` flags and `Valuation_Price_Alignment_Status` report whether the metric was aligned.

### 5.4 Fundamental collection and failure behavior

Fundamentals come from Yahoo quote metadata and use a seven-day cache by default. The collector requires a cache schema containing company metadata, raw valuation denominators, sector/industry, and provenance. It fetches at a throttled rate and retains stale cached rows on a transient request failure. A fundamental record is left-joined to technical rows:

```text
research universe = successfully collected technical symbols
merged frame      = technical frame LEFT JOIN fundamental frame on Symbol
```

Therefore, a fundamental failure does not shrink the ranked universe silently. Instead, `Fundamental_Record_Available=False`, missing fields decrease coverage, and the final policy caps high-conviction labels.

### 5.4.1 Statement-derived recovery and field provenance

Model 5.0 already downloads annual Yahoo income, balance-sheet, and cash-flow statements for its factor blocks. Quote metadata is convenient but sparse for many NSE issuers, so `apply_statement_fallbacks()` reuses that same issuer evidence for a deliberately small set of equivalent raw fields:

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

For raw close `C_t` and volume `V_t`, daily turnover is `T_t = C_t * V_t`. The collector exports:

```text
Avg_Turnover_INR       = mean(T_t over usable history)
Median_Turnover_20D    = median(T_t over trailing 20 sessions)
Turnover_P10_20D       = 10th percentile(T_t over trailing 20 sessions)
Median_Turnover_60D    = median(T_t over trailing 60 sessions)
Top5_Share_60D         = sum(largest five T_t in trailing 60) / sum(T_t in trailing 60)
Trading_Frequency_60D  = count(V_t > 0 in trailing 60) / observed trailing-60 sessions
```

Zero-volume sessions are retained so intermittent trading cannot look artificially liquid.

The collection-stage price-volume confirmation uses a standard 21-session Chaikin Money Flow calculation on adjusted prices:

```text
MFM_t  = (2 * Close_t - High_t - Low_t) / (High_t - Low_t)    # zero range -> 0
CMF_21 = sum(MFM_t * Volume_t) / sum(Volume_t), t in last 21 sessions
Return_20D = 100 * (AdjustedClose_t / AdjustedClose_{t-20} - 1)
```

`Demand_Proxy_Status` labels the result as accumulation proxy (`CMF_21 > 0` and return > 0), distribution proxy (both < 0), mixed, or unavailable. The label itself is not a separate score; the numeric technical `VOL` component below uses CMF, price return, and relative volume.

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

Financial values expressed as ratios use `0.20 = 20%`; debt-to-equity is consumed in Yahoo's percentage-style unit. Missing/non-numeric values receive zero points. The generic grid is:

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

Base expected growth uses a sector benchmark plus a size adjustment, clamped to 5%-25%. Sector benchmarks are Technology 18%, Communication Services/Healthcare 16%, Consumer Cyclical 15%, Industrials 14%, Financial Services 13%, Basic Materials/Real Estate 12%, Energy/Consumer Defensive 10%, Utilities 8%, and 15% fallback. Size adjustment is `-3%` for market cap >= 200,000 crore, `-1.5%` >= 20,000 crore, 0 >= 5,000 crore, else `+2%`.

For base FCF `FCF_0`, forecast growth `g`, terminal growth `g_T`, and discount rate `r`:

```text
FCF_t = FCF_{t-1} * (1 + g)
PV_forecast = sum(FCF_t / (1+r)^t, t=1..N)
Terminal_Value_N = FCF_N * (1+g_T) / (r-g_T)
DCF_Value = PV_forecast + Terminal_Value_N / (1+r)^N
```

The model requires positive reported FCF for blending. Missing FCF with positive revenue can create an 8%-of-revenue estimated FCF audit scenario, but it is not blend-eligible. Reported nonpositive FCF is preserved as `negative_fcf`, review-required, and not silently replaced with the revenue-margin estimate.

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

### 10.1 Upstream transcript analysis

A separate transcript worker discovers, extracts, cleans, segments, chunks, analyzes, and stores call sentiment. The daily screener only bulk-loads the latest cached record from Supabase; it does not download or re-analyze every transcript.

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

Weighted transcript aggregates use estimated token count as the weight. The stored overall score is:

```text
Overall_Transcript_Score = 0.25 * optimism
                         + 0.20 * management_confidence
                         + 0.20 * guidance_strength
                         + 0.20 * (100 - risk_intensity)
                         + 0.15 * answer_quality
```

Explicit guidance is categorical and conservative: lowered guidance dominates raised guidance, which dominates maintained guidance when present in different chunks.

### 10.2 Daily eligibility, decay, and blend

A transcript is score-eligible only if it belongs to the current reporting cycle, is not older than `TRANSCRIPT_MAX_EVIDENCE_AGE_DAYS=180`, and has nonzero weight. The raw recency factor is:

```text
w_age = exp(-ln(2) * age_days / half_life_days)          # default half life = 90 days
```

It is tapered before the next reporting-cycle transition:

```text
w_cycle = clamp(days_until_next_transcript_deadline / taper_days, 0, 1)
w_evidence = w_age * w_cycle                             # default taper = 20 days
Transcript_Blend_Weight = 0.15 * w_evidence
```

The exported `Transcript_Weighted_Score = 50 + (Transcript_Score - 50) * w_evidence` is an audit feature. The central policy uses `Transcript_Effective_Score` (the current-cycle stored score) plus the already-decayed blend weight.

Quality eligibility is an audit/high-conviction check, not a second numerical score:

```text
Transcript_Quality_Eligible = current-cycle eligible
                           AND Transcript_Score >= 55
                           AND (risk missing OR risk <= 60)
                           AND guidance != "lowered"
```

Missing, expired, prior-cycle, unconfigured, or unavailable transcripts are neutral; they do not receive a hidden rank tier. By default, a transcript is not required for STRONG BUY (`REQUIRE_TRANSCRIPT_FOR_STRONG_BUY=False`).

## 11. Authoritative evidence blend and recommendation policy

### 11.1 Stage equations

The finalizer begins with `Combined_Score` and writes `Core_Score`. It applies DCF symmetrically around neutral 50:

```text
Score_After_DCF = clamp(Core_Score + w_dcf * (DCF_score - 50), 0, 100)
```

Only `DCF_Blend_Eligible` rows with valid score and positive weight receive the adjustment. Default `w_dcf=0.10`.

Transcript evidence is deliberately downside-only:

```text
transcript_delta = min(w_tx * (Transcript_Effective_Score - 50), 0)
Evidence_Score = clamp(Score_After_DCF + transcript_delta, 0, 100)
```

A positive transcript is visible in the data but cannot promote a post-DCF rating. The finalizer exports exact contributions and whether positive evidence was intentionally not promoted.

### 11.2 Rating bands

| Score band | Rating |
|---:|---|
| >= 70 | STRONG BUY |
| >= 60 and < 70 | BUY |
| >= 50 and < 60 | HOLD |
| >= 40 and < 50 | REDUCE |
| < 40 | SELL |
| missing | UNRATED |

### 11.3 BUY gates

Any BUY failure sets the decision ceiling to `59.99`, which guarantees the published label cannot be BUY even if `Evidence_Score` is higher. Failures include:

1. Core score unavailable.
2. Any present coverage flag (`Coverage_Eligible`, fundamental coverage eligibility, technical coverage eligibility) is false.
3. `Data_Quality == LOW`.
4. Specialist model required but unavailable/data-limited.
5. Stale fundamental fallback.
6. At least two fundamental anomalies.
7. A dedicated financial model's specialized regulatory/quality evidence is ineligible.
8. When `REQUIRE_UPTREND_FOR_BUY=True` (default):
   - adjusted price or MA50 unavailable;
   - `Technical_Price <= MA50`;
   - MA50 slope unavailable or `< 0.0`;
   - three-month return unavailable or `<= 0.0`.

### 11.4 STRONG BUY gates

STRONG BUY inherits all BUY failures. Any remaining STRONG BUY failure sets the ceiling to `69.99`. Additional requirements are:

1. Revenue growth or earnings growth is at least 5%.
2. ADX is available and >= 20.
3. `+DI > -DI`.
4. `Technical_Score >= 55`.
5. Fundamental coverage >= 0.75 and technical coverage >= 0.90 when numeric coverage is present.
6. Specialized quality is eligible.
7. No fundamental anomaly at all.
8. By default, `DCF_Status != negative_fcf`.
9. If configured, a fresh quality transcript is required.

The policy collects every simultaneous failure, de-duplicates it, and exports JSON arrays, semicolon text, and counts. This makes a rating cap explainable rather than simply showing one first failure.

### 11.5 Ceiling and final decision

```text
Decision_Score_Ceiling = 59.99  if any BUY failure
                       = 69.99  if no BUY failure but any STRONG BUY failure
                       = 100.00 otherwise

Decision_Score = round_half_up(min(Evidence_Score, Decision_Score_Ceiling), 2)
Final_Score    = Decision_Score
Rating         = rating_from_score(Decision_Score)
```

`Evidence_Rating` is also exported to show the uncapped evidence band. A DCF or transcript contribution can lift `Evidence_Score`, but it cannot resurrect a candidate that failed an independent gate.

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
| `Investment_Rank` | `Decision_Score DESC`, `Evidence_Score DESC`, `Symbol ASC` | **Primary investment/research rank.** |
| `Rank` | alias of `Investment_Rank` | Backward-compatible main rank. |
| `Actionable_Rank` | `Portfolio_Actionable DESC`, `Investment_Rank ASC` | Execution-oriented presentation rank. |

The top stocks shown by the main CSV/report are `Rank=1...TOP_STOCKS_COUNT` in primary investment order. A stock with raw evidence 80 that fails a BUY gate is capped at 59.99 and will rank below a candidate with a higher decision score, even when the former has `Score_Rank=1`. This is intentional: raw evidence and decision eligibility are separate concepts.

The final execution overlay preserves investment rank inside the actionable/non-actionable buckets. It never uses transcript availability or liquidity as a hidden tie-break for primary rank.

## 13. Liquidity and portfolio actionability

### 13.1 Official NSE evidence

The provider downloads/caches NSE's monthly CM security category/mean-impact-cost file for EQ symbols. It recognizes Groups I, II, and III. Group I is treated as the liquid category and the official impact-cost reference order is Rs1 lakh.

### 13.2 Position-capacity calculation

For configured position target `P` (default Rs100,000) and participation rate `p` (default 1%):

```text
Max_One_Day_Order = Median_Turnover_20D * p
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

For a Group I candidate with direct Rs1 lakh impact-cost evidence and a target no larger than Rs1 lakh, effective build days are set to one rather than applying the conservative 1% turnover proxy. Group II/III are restricted. If official evidence is absent, turnover-based actionability is explicitly identified as a proxy.

No liquidity result can cap `Final_Score`, modify `Rating`, or change `Investment_Rank`; it only determines actionability and `Actionable_Rank`.

### 13.3 Emergency prefilter

The normally-disabled prefilter requires either Group I or, when official category is unavailable, both average and 20-day median turnover >= Rs50 lakh/day. It also requires raw current price >= configured minimum (default zero). This prefilter is an operational escape hatch and makes the evaluated research universe smaller; the run manifest records whether it was used.

## 14. Optional non-scoring overlays

### 14.1 Red flags

When enabled, `RedFlagEnricher` joins cached data such as issuer/trading severity, flag count, pledge/encumbrance fields, and source freshness. `RedFlagShadowSimulator` produces a hypothetical outcome **if the underlying evidence is confirmed**:

- severity 2 issuer/trading can cap a hypothetical rating at BUY;
- severity >= 3 can cap a hypothetical rating at HOLD;
- issuer severity >= 3 clips hypothetical score to at most 59.99.

These are `Shadow_*` fields only. Live `Rating`, `Final_Score`, and ranks remain unchanged because the feed is discovery evidence requiring primary-source verification.

### 14.2 News and FII/DII

After final ranking, the application fetches Google News RSS headlines for only the top `NEWS_SENTIMENT_TOP_N` rows (default 20). It counts fixed positive/negative whole-word lexicon hits and exports a display label. News does not feed the score.

FII/DII is presently an explicit placeholder and is logged, not scored. Earnings-surprise consensus is absent rather than approximated.

## 15. Output, observability, and reproducibility

### 15.1 Files and delivery

The standard run produces:

| Artifact | Purpose |
|---|---|
| `advanced_analysis_YYYYMMDD.csv` | Full ranked research universe with audit fields. |
| `advanced_analysis_YYYYMMDD.manifest.json` | Reproducibility manifest for the CSV. |
| `collection_diagnostics_YYYYMMDD.json` | Selected/collected/missing symbol sets, source state, calendar, and collection metadata. |
| Static dashboard output | Standalone HTML report generated by `InteractiveDashboard` and retained in the workflow artifact. |
| Supabase dashboard read model | `screener_runs`, current full `screener_snapshot` rows, and narrow long-lived `screener_history` rows consumed by the private web application. |
| Optional HTML/PDF/email/WhatsApp | Delivery layers; disabled by default for email/WhatsApp. |
| Production market-data cache | The original five paths: `price_cache.csv`, `fundamental_cache.csv`, `nse_liquidity_categories.csv`, `backtest_history.csv`, and `yfinance_cache/`. |
| `statement_cache.csv` | Annual-statement input, stored in a separate production or candidate cache namespace rather than the market-data composite. |
| Backtest history | Model-version-separated snapshot/outcome monitor when writes are enabled; it remains one of the five production composite-cache paths. |

### 15.2 Run manifest

`validation/reproducibility.py` builds a canonical secret-free manifest containing:

- schema version, UTC timestamp, Git SHA, dirty-worktree/status/diff hashes;
- model/policy/schema versions;
- SHA-256 of an allow-listed effective configuration;
- hashes/sizes of cache inputs and outputs;
- Python/platform/package versions;
- collection diagnostics and exact collection counts.

The CSV also carries run-level fields such as model/config hash, Git SHA, universe-source hash, market calendar version, and collection diagnostics hash.

### 15.3 Backtest boundary

`BacktestEngine` logs snapshots and later calculates realized returns only within the same `MODEL_VERSION`; it does not mix different model versions. This is necessary monitoring infrastructure but is not a complete point-in-time out-of-sample backtest: it does not itself solve survivorship bias, benchmark comparison, transaction costs, delistings, or look-ahead-control requirements.

### 15.4 GitHub Actions cache and candidate-isolation contract

The production composite cache keeps its original five-path declaration exactly:
`price_cache.csv`, `fundamental_cache.csv`, `nse_liquidity_categories.csv`,
`backtest_history.csv`, and `yfinance_cache/`. GitHub incorporates the declared path list into
an internal cache version, so adding `statement_cache.csv` there would make otherwise valid
production entries unreachable. The daily workflow therefore restores and saves statements
under a separate production-only statement-cache key.

That namespace was originally initialized by the one-shot `seed-production-statement-cache.yml`
workflow, which extracted and validated `candidate/statement_cache.csv` from the artifact of an
already successful candidate validation and saved it under the production statement-cache prefix.
The initial promotion used green run `31685056109` at
`fa9d3094129b9540717a67fda040449340d7dec1`; that seed was cache bootstrap, not a second model
validation or evidence of predictive performance.

**Retired 2026-08-19.** The seeding workflow has been removed now that the scheduled run sustains
its own statement cache: it restores under the `stock-screener-statements-v1-` prefix and saves
the refreshed file on every scheduled run, keeping the entry inside GitHub's seven-day eviction
window. A cold rebuild remains possible without it — `STATEMENT_FETCH_MAX_SYMBOLS_PER_RUN` is
`2500` on scheduled runs so a single run can fetch the whole NSE universe — but a cold first run
may land below the 95% coverage floor and produce degraded factor output until coverage recovers.
The workflow remains in git history and can be restored with
`git checkout <sha> -- .github/workflows/seed-production-statement-cache.yml`.

Scheduled production independently enforces at least 95% statement coverage before scoring. If
that guard fails, its `always()` cache checkpoint preserves successfully fetched records for the
next attempt without publishing a partial cross-section.

**`candidate-model-validation.yml` retired 2026-08-19,** having served its purpose once Model 5.0
reached scheduled production. Its isolation contract is recorded here because the same guarantees
apply to any future candidate workflow, and because the manual-dispatch path of
`daily-stock-screener.yml` still relies on the same isolation reasoning.

The candidate workflow could read production vendor inputs but could not update either production
cache namespace. When `baseline_run_id` was supplied, it validated the baseline report artifact
before dependency installation and expensive screening, restored the exact five-path production
cache saved by that run, and verified that the baseline and candidate used the same completed
price session. Without a baseline ID it could use the latest production cache only as a read-only
seed.

Candidate statements had their own branch-scoped cache. A run could restore its accumulated
tranches or explicitly seed from the statement artifact of an earlier candidate run, and it
saved a successful statement backfill immediately after screening even if comparison later
failed. Candidate transcript parity did require the Supabase URL and service-role secret, but
`SUPABASE_READ_ONLY=True` rejected non-GET requests. The job did not publish to Supabase,
append production backtests, send notifications, or include secrets in caches or artifacts.
A factor-model comparison was refused until statement coverage reached at least 95% of the
full candidate universe.

### 15.5 Supabase publication and private web dashboard

The production web path is intentionally downstream of the research CSV:

```text
scheduled GitHub Actions
  -> advanced_analysis_YYYYMMDD.csv + manifest + diagnostics
  -> DashboardPublisher (service role; scheduled runs only)
  -> Supabase/Postgres read model
       screener_runs       one row per completed trading session
       screener_snapshot   typed query columns + complete source row in payload jsonb
       screener_history    narrow daily series retained for movers/history
  -> Next.js 16 application on Vercel
       authenticated server reads under Supabase RLS
       screener / movers / run health / stock detail / decision audit
```

The publisher resolves `run_date` from `Price_Bar_As_Of`, then `Analysis_As_Of`, and only then
the filename. This keeps renamed or replayed files from inventing a calendar date. It reports
duplicate symbols and coercion drift, maps the fields needed for filtering/indexing into typed
columns, and stores every original CSV field in `payload`. A new audit-only export therefore
appears in drill-down without a database migration; only a field that must be filtered or
indexed needs a typed-column migration.

Publication uses a recoverable reserve/write/complete protocol because PostgREST cannot wrap
several chunked requests in one client transaction:

1. Refuse replacement of a completed same-date run by default. Scheduled publication passes
   `--if-exists skip`, which returns success and leaves the immutable snapshot unchanged.
2. Reclaim a prior zero-row reservation after cleaning orphan history and cascade-deleting
   partial snapshot chunks.
3. Insert a zero-row parent reservation, upsert snapshot chunks, remove stale same-date symbols,
   upsert slim history, and only then write the complete run metadata with a nonzero row count.
4. On a write failure, compensate by removing partial history/reservation state and fail loudly.
5. Prune old full snapshots only after completion. Prune failure is logged as housekeeping and
   does not invalidate the already-visible new run. The default retains two full snapshots;
   narrow history remains available for the movers view.

`latest_completed_run()` excludes zero-row reservations, so the site and schedule guard never
mistake an interrupted publish for a valid run. If Supabase is unavailable, publication is the
last workflow step: the CSV artifact and warmed caches already exist, and the site continues to
serve the previous completed run behind its freshness warning.

Access is invite-only. Supabase Auth establishes the browser session, `dashboard_allowlist` and
server-side `requireAccess()` enforce membership, and row-level security is the final data gate.
The public anon key is expected in the browser; the service-role key exists only in GitHub
Actions. RLS helper calls are wrapped as scalar subqueries so Postgres evaluates access once per
statement rather than once per returned row.

Company logos are identifiers, not stored image blobs. The collector publishes the normalized
issuer website as `logo_domain`. Missing domains on an existing snapshot were filled through Yahoo
website metadata by the resumable `backfill-logo-domains.yml` workflow, **retired 2026-08-19** once
the backfill completed; its worker `workers/logo_domain_backfill.py` remains in the tree and can
still be run directly. It patches only `logo_domain` and carries the existing non-null `payload`,
so drill-down evidence is preserved.
The browser requests the image from Brandfetch's CDN using the public
`NEXT_PUBLIC_BRANDFETCH_CLIENT_ID`. Missing domains, absent client configuration, and CDN/image
errors all fall back to the ticker initial. No Brandfetch secret key or company image is stored
in Supabase.

The stock detail page treats the published row as authoritative. Its Decision audit exposes the
policy ceiling and exact gate reasons, missing fundamental/technical fields, factor coverage,
and the serialized Value input sources. Technical display distinguishes `Price vs MA50` from
`MA50 slope (20 sessions)`, while debt/equity is normalized from Yahoo percentage points to the
human-readable ratio multiple. The application tab icon reuses the same gauge-and-bars
`BrandMark` as the shell rather than the framework's default favicon.

## 16. Configuration defaults that materially change decisions

| Parameter | Default | Decision impact |
|---|---:|---|
| Fundamental/technical blend | 70% / 30% | Core score construction. |
| `FUNDAMENTAL_MIN_COVERAGE_FOR_BUY` | 0.55 | Below it prevents BUY. |
| `TECHNICAL_MIN_COVERAGE_FOR_BUY` | 0.75 | Below it prevents BUY. |
| Strong coverage floors | 0.75 fundamental / 0.90 technical | Below them prevents STRONG BUY. |
| `REQUIRE_UPTREND_FOR_BUY` | true | Requires price > MA50, nonfalling MA50, positive 3M return. |
| `STRONG_BUY_MIN_GROWTH` | 0.05 | Revenue or earnings growth floor. |
| `STRONG_BUY_MIN_TECH_SCORE` | 55 | Technical score floor. |
| `STRONG_BUY_MIN_ADX` | 20 | ADX floor; `+DI > -DI` also required. |
| Sector relative enabled / weight / peers | true / 0.5 / 5 | Blends generic absolute points with peer percentiles. |
| DCF enabled / blend weight | true / 0.10 | Symmetric centered DCF evidence stage. |
| DCF discount/terminal growth | 11% / 4% | DCF scenario valuation. |
| Transcript enabled / base weight | true / 0.15 | Decayed downside-only transcript evidence stage. |
| Transcript max age / half life | 180d / 90d | Current-cycle transcript eligibility and weight. |
| Transcript required for STRONG BUY | false | Optional additional high-conviction gate. |
| Target position / participation | Rs100,000 / 1% | Liquidity actionability only. |
| Liquidity prefilter | false | If enabled in full scan, reduces the research universe before scoring. |

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
| No transcript / prior cycle / expired transcript | Neutral evidence; no implicit rank penalty or priority. |
| Positive transcript | Exported but cannot numerically promote score. |
| High raw score fails trend/coverage gate | Published decision score is ceiling-capped to 59.99 or 69.99. |
| Liquidity fails | Primary rank/rating remains; actionability is false and execution rank moves it behind actionable names. |
| Red-flag feed shows severity | Shadow-only review/counterfactual; no live rating change. |

## 18. Code-level source of truth

This document describes current implementation behavior. The authoritative files for future maintenance are:

1. `app.py` — composition root and execution order.
2. `screener/runtime.py` — environment-backed defaults and feature flags.
2b. `screener/statements.py`, `screener/benchmark.py`, `screener/factors.py` — Model 5.0
   statement collection, benchmark/regime, and factor blocks (see section 20).
3. `screener/data_collection.py` — collection, completed-bar policy, valuation alignment, liquidity metrics, and fundamentals cache.
4. `screener/market_data.py` — technical indicator algorithms and cache validation.
5. `screener/scoring.py` — fundamental/technical point functions, coverage, specialist models, and peer-relative scoring.
6. `screener/valuation.py` — reverse-DCF scenario and evidence contract.
7. `scoring/transcript_enricher.py`, `sentiment/*.py`, and `transcripts/periods.py` — transcript feature creation, eligibility, and execution overlay rank.
8. `screener/recommendation.py` — final decision mathematics, gates, ceiling rules, stability diagnostics, and primary rank implementation.
9. `screener/liquidity.py` — NSE evidence and actionability math.
10. `red_flags/*.py` — non-live risk shadow behavior.
11. `validation/reproducibility.py` — run manifest and canonical configuration hashing.
11b. `workers/scheduled_session_guard.py` — completed-session publication guard for scheduled work.
11c. `workers/dashboard_publisher.py` and `storage/dashboard_repository.py` — Supabase read-model mapping, reservation protocol, immutable-date policy, retention, and logo-domain patching.
11d. `storage/dashboard_schema.sql` — typed/read payload schema, RLS, movers view, allowlist functions, and snapshot pruning.
11e. `dashboard/app`, `dashboard/components`, and `dashboard/lib` — authenticated Next.js read paths, visual semantics, queries, and formatting.
11f. `workers/logo_domain_backfill.py` — resumable Yahoo website-domain resolution for Brandfetch identifiers, run directly since `backfill-logo-domains.yml` was retired.
12. `tests/test_technical_scoring.py`, `tests/test_recommendation.py`, `tests/test_liquidity.py`, and `tests/test_valuation.py` — executable behavioral specifications.
13. `tests/test_statements.py`, `tests/test_benchmark.py`, `tests/test_factors.py`,
    `tests/test_factor_policy.py`, `tests/test_trend_risk_features.py`,
    `tests/test_factor_wiring.py` — executable specifications for Model 5.0.

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

## 20. Model 5.0 factor architecture (scheduled production)

**Status:** scheduled production uses model `5.0.0`, recommendation policy `5.0.0`, and
additive output schema `4.2.0`. The daily workflow enables the factor switch only for scheduled
runs; local execution and a manual dispatch of that workflow retain the 4.x default. Candidate
run `31685056109` supplied operational full-universe evidence, while point-in-time,
out-of-sample predictive validation remains pending.

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

Model 5.0 keeps the 70/30 *philosophy* — 70% accounting evidence, 30% market evidence — but
makes each block economically separable.

### 20.2 Blocks and weights

```text
Research_Score_Raw = 0.35 * Quality
                   + 0.20 * Growth
                   + 0.15 * Value
                   + 0.25 * Momentum
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
| Quality (generic) | 0.35 | ROIC .20 up, gross profit/assets .15 up, OCF/assets .13 up, FCF/assets .09 up, accruals/assets .10 down, interest coverage .05 up, net debt/EBITDA .05 down, operating-margin stability .08 down, earnings stability .08 down, asset growth .04 down, 3Y dilution .03 down |
| Quality (financial) | 0.35 | ROE .28 up, ROA .22 up, equity/assets .20 up, earnings stability .15 down, profit margin .15 up |
| Growth | 0.20 | Revenue CAGR 3Y .25 up, EPS CAGR 3Y .20 up, revenue acceleration .15 up, EPS acceleration .15 up, margin direction .15 up, cash conversion .10 up |
| Value | 0.15 | Earnings yield .25 up, FCF yield .25 up, EBIT/EV .20 up, book yield .15 up, reverse-DCF score .15 up |
| Momentum | 0.25 | Risk-adjusted 12-1 .30 up, risk-adjusted 6-1 .25 up, 6M sector-relative .20 up, 6M market-relative .15 up, signed trend quality .10 up |
| Risk | 0.05 | Annualised volatility .25 down, max 1Y drawdown .20 up, trading frequency .20 up, downside deviation .15 down, gap risk .10 down, return concentration .10 down |

Notes on specific inputs:

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

**This makes Model 5.0 ratings explicitly relative,** which is a genuine semantic change from
4.x and has two consequences that remain part of the production contract:

- In any universe, roughly 40% of rows score below 50 and are labelled REDUCE or SELL. On a
  40-name blue-chip watchlist that reads as absurdly bearish; on a full-NSE run it is closer to
  the intended meaning. **Model 5.0 is designed for full-universe runs.**
- "Top 30% of a collapsing market" would otherwise be published as STRONG BUY. What prevents
  that is not the score but the *absolute* protections: the market-regime overlay (20.6) and the
  hard trend, quality, coverage and liquidity gates (20.5), all of which fail closed.

Set `FACTOR_SCORE_AS_PERCENTILE=False` to publish the raw blend instead; the rating bands then
need recalibrating.

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
| Benchmark index (`^CRSLDX`, fallback `^NSEI`) | `yf.download` | available, ~493 sessions |

Yahoo's quote metadata supplies **none** of these: it has no total assets, no EBIT, no gross
profit, no cash-flow history and no multi-year series, and it omits `returnOnEquity` and
`returnOnAssets` outright for part of the universe (RELIANCE and HDFCBANK both returned `None`
in the audit).

**Collection cost.** In candidate run `31674195181`, a cold full-NSE screen spent about 59
minutes fetching fundamentals for 2,310 symbols and about 15.5 minutes on the first bounded
statement tranche (600 attempted, 594 usable); the complete screener step took about 80 minutes.
The dominant cost was therefore the cold fundamental fetch, not the statement fetch. Statements
restate quarterly at most, so `STATEMENT_CACHE_MAX_AGE_DAYS` defaults to 90 and
`STATEMENT_FETCH_MAX_SYMBOLS_PER_RUN` bounds each run's backfill (2,500 by runtime default,
400 for an isolated manual-daily run, and 600 by default in candidate validation). Candidate
validation also accepts 2,500 for a deliberate one-time
full-universe completion. Symbols not yet backfilled report no statement evidence and fail
closed, while the comparison step refuses factor-model evidence below 95% universe coverage.

Statements are deliberately **not** a sixth path in the production market-data composite.
The failed validation run changed that path list, which changed GitHub's hidden cache version
and forced the 59-minute cold fundamental refill. Production now keeps the original five-path
composite and uses a separate production statement-cache namespace. Candidate runs use a
different, branch-scoped statement namespace, may seed it from a prior candidate artifact, and
checkpoint each successful tranche before any later comparison can fail. This preserves the
bounded backfill without allowing a candidate to mutate production cache state.

### 20.5 Gates

Model 5.0 keeps every shared data-integrity gate from section 11.3 (core score present, price
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

**STRONG BUY** (inherits every BUY failure; further failures cap at `69.99`):

| Gate | Threshold |
|---|---|
| Quality / Growth / Momentum percentile | `>= 70` / `>= 60` / `>= 70` |
| Moving-average stack | `Price > MA50 > MA200` |
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
| NEUTRAL | STRONG BUY additionally requires momentum percentile `>= 85` |
| RISK_OFF | STRONG BUY disabled; BUY additionally requires momentum percentile `>= 90` |

The overlay changes **deployment conviction only**. It never edits a factor score, so the
research ranking stays fully visible and auditable in every regime. This is locked by
`test_regime_never_edits_the_research_score`.

### 20.7 Separated decision views and eligibility-class ranking

Collapsing every gate failure onto an identical `59.99` creates a large artificial cluster and
destroys the ordering *within* it — ranking that cluster by `Decision_Score` sorts a column that
is constant by construction and falls through to the symbol tie-break, i.e. **alphabetical order
presented as investment merit**. Model 5.0 publishes separate views instead:

| Field | Meaning |
|---|---|
| `Research_Rating` | Uncapped research view (band of `Evidence_Score`) |
| `Policy_Eligible_Rating` | The published, gate-capped label (equals `Rating`) |
| `Execution_Status` | `ACTIONABLE` / `NOT_ACTIONABLE` |
| `Primary_Gate` | Most severe binding reason, as a stable slug (`BELOW_MA200`, `LOW_QUALITY`, `ILLIQUID`, ...) |
| `Gate_Severity` | Count of simultaneous failures |
| `Eligibility_Class` | `0` clears every gate, `1` BUY-eligible, `2` policy-capped, `3` unscorable |

`Primary_Gate` answers "what is stopping this row from being rated higher", so a BUY-eligible row
can still report a STRONG BUY gate. Patterns are scanned in severity order, not in the order the
failures happened to be appended.

With `RANK_BY_ELIGIBILITY_CLASS=True`:

```text
Investment_Rank = sort(Eligibility_Class ASC, Research_Score DESC,
                       Gate_Severity ASC, Symbol ASC)
```

`Decision_Score`, `Final_Score` and the ceiling logic are unchanged, so every existing consumer
keeps working.

### 20.8 Known gap: financial-sector regulatory evidence

`Gross_NPA`, `Net_NPA`, `Capital_Adequacy` and `Solvency_Ratio` are declared as required
specialist evidence (section 7.6) and are required by `specialized_quality_gate`, but **no
collector in this repository has ever populated them** and Yahoo does not publish them. The
practical effect, in 4.x as well as 5.0, is that **every bank, NBFC and insurer is permanently
barred from BUY** — silently removing the largest sector of the Indian market from the actionable
universe. This was confirmed on a live run: all 9 financial rows failed with
`missing specialized quality data`.

Model 5.0's financial quality template scores these companies correctly from statement evidence
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

Model 5.0's BUY floor is 0.70, so **banks and NBFCs fail on coverage even with the flag set**;
insurers clear BUY but can never reach the 0.75 STRONG BUY floor. Under 4.x the 0.55 BUY floor is
cleared, so there the specialist gate alone is the binding constraint.

Fully closing the gap therefore needs one of:

1. an NPA/CAR/solvency feed from exchange filings — the correct fix, and the only one that makes
   the evidence real rather than merely uncounted; or
2. removing structurally uncollectable fields from the coverage denominator, so coverage measures
   *how much of what is knowable is known*. This changes 4.x behaviour too and should be a
   separate, reviewed change rather than a side effect of the Model 5.0 rollout.

**A feed has been scoped and verified — see `docs/financial_regulatory_data_feed_scope.md`.**
Summary: NSE's `corporates-financial-results` API tags bank filings and serves them under a
`BANKING_` XBRL taxonomy carrying `PercentageOfGrossNpa` and `PercentageOfNpa`, verified against
reported figures for HDFCBANK, SBIN and AXISBANK. That unblocks the 41 listed banks for about a
day of work. The consolidated filing returns `0.00` for every NPA tag, so a naive reader would
publish pristine asset quality for every bank — the scope document treats that as a required
test, not a caveat.

NBFC asset quality and capital adequacy are **not** in any XBRL taxonomy, but they are in the
results PDF, which NSE exposes through `corporate-announcements` and which PyMuPDF (already a
dependency) can read. Measured over 12 NBFCs: CRAR detected in 83%, gross/net NPA in 50%, where
the 50% is a detection limit — filers write "Stage III", "GNPA" and "Gross Stage 3 assets"
interchangeably — rather than an availability limit. That route also closes the CRAR gap for
banks, which no XBRL carries. It is viable but is a 1-2 week parsing project with permanent
layout maintenance, and it must use coordinate-based table extraction: labels and values are
separated in the text stream, and a mis-paired CRAR would pass the regulatory gate with a
fabricated number.

### 20.9 Validation status and protocol

Measured on a 40-name large-cap watchlist, 4.x baseline vs Model 5.0 on identical vendor inputs:
Spearman rank correlation **0.62**, top-20 Jaccard **0.60**, 5 entrants and 5 exits. The model
re-ranks materially, which is the point — and exactly why it must not be promoted on a smoke test.

**Nothing here is evidence that Model 5.0 predicts returns better than 4.x.** Before making
predictive-performance claims, run the pre-declared grid from the proposal (A: 4.x baseline,
B: factorised 70/30, C: 60/40 with
MA200 gate, D: proposed without MA200 gate, E: proposed with regime overlay) under expanding
walk-forward validation with a final untouched test period, and evaluate forward 1/3/6/12-month
returns, decile portfolios, excess return vs Nifty 500 TRI, rank information coefficient, hit
rate, maximum drawdown, turnover, transaction costs, sector/size exposure, regime-split
performance, and rating stability.

Note that `screener/statements.py` derives from the statements Yahoo publishes *today* and makes
no attempt to reconstruct what was knowable on a past date, so it is suitable for a forward
screen but **not** for a look-ahead-free historical backtest without a point-in-time
fundamentals source. This is the single largest obstacle to executing the validation protocol
above and should be scoped before interpreting Model 5.0 as predictively validated.

The isolated candidate workflow adds an operational guard, not a predictive claim: comparison
fails below 95% statement coverage so an alphabetical or otherwise partial backfill cannot be
mistaken for a full-universe result. A successful screen checkpoints its candidate-only
statement tranche before that guard or a later baseline comparison can fail. For transcript
parity the workflow may bulk-read Supabase using the service-role secret, but read-only mode
rejects every write and the secret is never placed in a manifest, cache, or artifact.

Full-NSE candidate run `31685056109` completed successfully at the approved candidate commit. Its
cache contained 2,284 unique statement rows; 2,283 matched the 2,301-row candidate universe and
were usable (99.22% coverage). This is operational acceptance evidence
only: it shows that the pipeline runs, the cross-section is substantially complete, and the
comparison tooling works.
It neither estimates future returns nor demonstrates superiority over 4.x. Scheduled production
therefore exports a validation status that continues to state that point-in-time,
out-of-sample validation is pending.

### 20.10 Model 5.0 configuration reference

| Parameter | Runtime default / scheduled override | Effect |
|---|---:|---|
| `FACTOR_MODEL_ENABLED` | false / true | Master switch; GitHub's scheduled production run explicitly enables it while manual daily dispatch remains false |
| `MODEL_VERSION` / `RECOMMENDATION_POLICY_VERSION` / `OUTPUT_SCHEMA_VERSION` | local model/policy `4.0.0-candidate`; scheduled model/policy `5.0.0`; schema `4.2.0` | Scheduled model, policy, and additive export contracts are versioned independently |
| `FACTOR_WEIGHT_{QUALITY,GROWTH,VALUE,MOMENTUM,RISK}` | .35/.20/.15/.25/.05 | Block blend |
| `FACTOR_SCORE_AS_PERCENTILE` | true | Publish the blend as a cross-sectional percentile |
| `FACTOR_SECTOR_NEUTRAL` / `FACTOR_MIN_SECTOR_PEERS` | true / 8 | Rank inside sector when it is large enough |
| `FACTOR_MIN_BLOCK_COVERAGE` | 0.50 | Block coverage floor for BUY |
| `FACTOR_VALUE_QUALITY_FLOOR_PCT` / `FACTOR_VALUE_CEILING_WHEN_LOW_QUALITY` | 30 / 50 | Value-trap cap |
| History/cache contract / `LEGACY_HISTORY_WINDOW_SESSIONS` | 4.x: 6mo/v6; Model 5.0: 2y/v7; 126 | Model-selected download depth and cache schema; six-month feature pinning applies to the longer Model 5.0 frame |
| `BENCHMARK_INDEX_SYMBOL` / `BENCHMARK_INDEX_FALLBACK` | ^CRSLDX / ^NSEI | Relative strength and regime source |
| `MARKET_REGIME_ENABLED` / `MARKET_REGIME_MA_SESSIONS` / `MARKET_REGIME_NEUTRAL_BAND_PCT` | true / 200 / 2.0 | Regime classification |
| `REQUIRE_MA200_TREND_FOR_BUY` / `BUY_MA200_TOLERANCE` | true / 0.98 | Trend gate and hysteresis band |
| `BREAKDOWN_CONFIRM_SESSIONS` | 10 | Confirmed-breakdown persistence |
| `BUY_MIN_QUALITY_PCT` / `STRONG_BUY_MIN_{QUALITY,GROWTH,MOMENTUM}_PCT` | 40 / 70,60,70 | Factor percentile floors |
| `FACTOR_FUNDAMENTAL_MIN_COVERAGE_FOR_BUY` / `FACTOR_TECHNICAL_MIN_COVERAGE_FOR_BUY` | 0.70 / 0.90 | Tightened BUY coverage |
| `REQUIRE_LIQUIDITY_FOR_BUY` | true | Execution liquidity as a BUY gate |
| `RANK_BY_ELIGIBILITY_CLASS` | true | Eligibility-first primary ranking |
| `FACTOR_FINANCIAL_STATEMENT_QUALITY_SUFFICIENT` | false | See 20.8 — risk-policy decision |
| `FACTOR_MIN_STATEMENT_UNIVERSE_COVERAGE` | 0.95 | Scheduled production fails before scoring and side effects if usable statement evidence covers less than 95% of the research universe |
| `STATEMENT_CACHE_MAX_AGE_DAYS` / `STATEMENT_FETCH_MAX_SYMBOLS_PER_RUN` | 90 / 2,500 scheduled (400 manual daily) | Statement cache TTL and recovery budget; candidate workflow defaults to 600 and allows 2,500 for one-time completion |
