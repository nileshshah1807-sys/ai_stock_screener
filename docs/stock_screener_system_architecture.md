# AI Stock Screener — As-Built System Architecture Design

- **Status:** implementation-derived design document
- **Scope:** current `app.run_daily_analysis()` production path and its supporting modules
- **Model defaults documented:** `4.0.0-candidate` / recommendation policy `4.0.0-candidate`
- **Last reviewed against code:** 2026-08-11

> **Research-model boundary.** This application produces deterministic research ranks and heuristic rating labels. `Rating`, `Decision_Score`, and `Final_Score` are not forecasts of return, fair value, or probability of profit. The configured `Model_Validation_Status` explicitly says point-in-time, out-of-sample validation is pending. The system's purpose is to make the screening logic auditable, reproducible, and reviewable—not to make an unvalidated investment-performance claim.

## 1. Executive summary

The application is an NSE equity research screener. It creates one row per successfully collected market-data symbol, derives a core score from fundamentals and technicals, applies independent DCF and transcript evidence, then applies hard policy gates before it ranks the result set. The primary rank is **not** a simple sort of raw score: it is ordered by the post-gate `Decision_Score` first, then uncapped evidence, then ticker symbol.

The main design principles implemented in the code are:

1. **Research universe first, execution overlay later.** The default full-NSE run retains the broad successfully collected universe; liquidity normally affects `Actionable_Rank`, not `Rating`, `Final_Score`, or primary `Rank`.
2. **Completed-bar consistency.** Each price-sensitive technical feature uses the same completed NSE daily bar. Raw `Current_Price` is retained for traded-value/valuation display; adjusted `Technical_Price` is used for returns, indicators, and chart gates.
3. **Score/evidence/policy separation.** Scoring, DCF, transcripts, liquidity, and red flags are evidence producers. Only `RecommendationPolicy` publishes canonical score, rating, eligibility, gate, and rank fields.
4. **Fail-closed high conviction.** Missing coverage, stale fundamentals, invalid specialist-model evidence, multiple data anomalies, and weak trend structure cap a candidate below BUY or STRONG BUY even if its raw score is high.
5. **Deterministic audit trail.** Stable sort order, decimal half-up rounding, collection diagnostics, output manifests, configuration hashing, and per-symbol gate reasons are exported.

## 2. Architecture overview

```text
                                  External sources
          ┌──────────────────────────────────────────────────────────────┐
          │ NSE equity master / monthly liquidity category & impact cost │
          │ Yahoo Finance via yfinance: 6-month OHLCV + fundamentals     │
          │ Supabase: precomputed transcript / red-flag records          │
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
| Collection | `screener/data_collection.py::StockDataCollector` | NSE universe, Yahoo 6-month OHLCV, cache reuse, Yahoo fundamentals, collection diagnostics. | No. |
| Technical calculation | `screener/market_data.py::TechnicalEnhancer` | RSI, ADX/+DI/-DI, StochRSI, ATR, returns. | No. |
| Liquidity source | `screener/liquidity.py::NSELiquidityProvider` | Joins NSE monthly Group I/II/III and Rs1 lakh mean impact cost. | No. |
| Core model | `screener/scoring.py::StockScorer` | Fundamental/technical component scores, sector-relative comparison, coverage, specialist quality checks. | Exports only provisional `Core_*` diagnostics. |
| Valuation evidence | `screener/valuation.py::ReverseDCFModel` | Reverse-DCF diagnostics and blend-eligible valuation score. | No. |
| Transcript evidence | `scoring/transcript_enricher.py::TranscriptSentimentEnricher` | Loads cached sentiments and establishes recency/cycle eligibility. | No. |
| Decision policy | `screener/recommendation.py::RecommendationPolicy` | Evidence blend, policy gates, ceilings, ratings, stability diagnostics, primary ranks. | **Yes; sole authority.** |
| Execution overlay | `LiquidityQualityEnricher` and `rank_actionable_recommendations` | Position-size actionability and `Actionable_Rank`. | No. |
| Risk shadow layer | `red_flags/enricher.py`, `red_flags/shadow.py` | Cached red flags and counterfactual outcomes if confirmed. | No. |
| Outputs | `screener/reporting.py`, `validation/reproducibility.py` | Dashboard/report delivery, CSV, provenance manifest and hashes. | No. |

## 4. End-to-end run sequence

`app.run_daily_analysis()` executes the following order. This order matters because later evidence is allowed to modify evidence score but not bypass gates.

1. Instantiate `Config`, determine `analysis_now` in `Asia/Kolkata` by default, and initialize cache folders.
2. Build the universe through `StockDataCollector.get_comprehensive_stock_list()`.
3. Download/reuse six months of OHLCV data; retain only symbols with a valid completed and aligned daily bar and enough usable history.
4. Join NSE liquidity categories and impact-cost evidence once for the collected symbols.
5. Apply the liquidity prefilter only when all of these are true: `LIQUIDITY_FILTER_ENABLED`, `SCAN_ALL_NSE`, and `PREFILTER_RESEARCH_UNIVERSE_BY_LIQUIDITY`. The default is **not** to prefilter.
6. Fetch or reuse fundamentals and left-join them to the technical universe. A fundamental miss does not delete a technically collected symbol; it becomes missing/limited evidence and is later prevented from receiving BUY conviction.
7. Recalculate price-dependent valuation ratios using the same completed close used for price technicals.
8. Run `StockScorer.score_all_stocks()` to create `Fundamental_Score`, `Technical_Score`, `Combined_Score`, `Core_Score`, coverage, component, model, anomaly, and provisional core fields.
9. If enabled, run `ReverseDCFModel.enrich()`.
10. If enabled, load precomputed transcript evidence. A transcript failure is fatal by default (`TRANSCRIPT_FAIL_ON_ERROR=True`), but can be configured to log and skip.
11. Run `finalize_recommendations()`: the sole writer of canonical decision fields and primary research ranks.
12. Optionally attach red-flag records and generate a shadow-only counterfactual.
13. Add liquidity actionability, then generate `Actionable_Rank` without changing the primary investment ordering.
14. Add model/config/run provenance, fetch display-only news sentiment for the already-ranked top N rows, write CSV/manifest/diagnostics/dashboard, and optionally send reports.
15. Optionally append the result to a model-version-separated backtest history.

## 5. Research universe, data contracts, and collection controls

### 5.1 Universe selection

- In full-scan mode (`SCAN_ALL_NSE=True`), the collector retrieves NSE's `EQUITY_L.csv`, adds a fixed liquid-name safety list, normalizes symbols, and sorts them.
- If the master file fails, the built-in safety list remains available.
- In watchlist mode (`SCAN_ALL_NSE=False`), the configured `CUSTOM_WATCHLIST` replaces the full universe.
- Collection diagnostics persist the selected, requested, collected, failed, and missing symbols. This prevents a different network-collected cross-section from appearing reproducible merely because code/config were unchanged.

### 5.2 Completed market-bar policy

Daily data is collected from Yahoo Finance with `auto_adjust=False`; the collector uses both raw and adjusted series deliberately:

| Purpose | Price scale | Column / use |
|---|---|---|
| Trading value, liquidity turnover, valuation/display close | raw daily close | `Current_Price` |
| Returns, moving averages, RSI, MACD, ADX, ATR, Bollinger position, chart gates | split/dividend-adjusted OHLC | `Technical_Price` and technical columns |

A bar is eligible only if it is the latest expected completed NSE session:

- Default time zone: `Asia/Kolkata`.
- Daily session completion cutoff: `16:15` IST.
- Before the cutoff, today's bar is excluded unless the explicit `ALLOW_PROVISIONAL_MARKET_BARS` escape hatch is enabled.
- After the cutoff, a normal NSE session needs today's complete bar; weekends and configured NSE holidays use the prior expected session.
- A lagging/incomplete price bar is not mixed into the cross section: that symbol is excluded from technical collection for the run.
- The price cache is accepted only when its schema, indicator version, max age, source fetch age, completion flag, and expected session are all current.

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
| Dashboard output | Interactive report generated by `InteractiveDashboard`. |
| Optional HTML/PDF/email/WhatsApp | Delivery layers; disabled by default for email/WhatsApp. |
| `price_cache.csv`, `fundamental_cache.csv`, `nse_liquidity_categories.csv` | Reusable cached inputs. |
| Backtest history | Model-version-separated snapshot/outcome monitor when writes are enabled. |

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
| Price bar lags expected session | Symbol is not admitted to the technical universe for that run. |
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
3. `screener/data_collection.py` — collection, completed-bar policy, valuation alignment, liquidity metrics, and fundamentals cache.
4. `screener/market_data.py` — technical indicator algorithms and cache validation.
5. `screener/scoring.py` — fundamental/technical point functions, coverage, specialist models, and peer-relative scoring.
6. `screener/valuation.py` — reverse-DCF scenario and evidence contract.
7. `scoring/transcript_enricher.py`, `sentiment/*.py`, and `transcripts/periods.py` — transcript feature creation, eligibility, and execution overlay rank.
8. `screener/recommendation.py` — final decision mathematics, gates, ceiling rules, stability diagnostics, and primary rank implementation.
9. `screener/liquidity.py` — NSE evidence and actionability math.
10. `red_flags/*.py` — non-live risk shadow behavior.
11. `validation/reproducibility.py` — run manifest and canonical configuration hashing.
12. `tests/test_technical_scoring.py`, `tests/test_recommendation.py`, `tests/test_liquidity.py`, and `tests/test_valuation.py` — executable behavioral specifications.

## 19. Recommended interpretation workflow

For a reviewer examining an exported top-ranked row:

1. Start with `Rank`, `Investment_Rank`, `Decision_Score`, `Rating`, and `Gate_Failures` to understand the published decision.
2. Compare `Evidence_Score` with `Decision_Score` and `Decision_Score_Ceiling` to determine whether a policy cap changed the rank.
3. Inspect `Fundamental_Score`, `Technical_Score`, `Fundamental_Model`, coverage fields, component columns, and anomalies to identify core drivers.
4. Inspect `DCF_*` and `Transcript_*` contribution/eligibility columns separately; they are overlays, not substitutes for a passing core policy gate.
5. Inspect `Portfolio_Actionable`, liquidity group/impact cost, build days, and `Actionable_Rank` before treating a high research rank as executable for a target size.
6. Inspect `Decision_Stability_Status`, margins, stale/cache/price-bar provenance, and red-flag shadow fields before interpreting a boundary result as robust.
7. Use the adjacent manifest and diagnostics file to reproduce the exact configuration, code state, source universe, and cached inputs.
