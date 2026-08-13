# Model methodology and evidence audit

Last reviewed: 2026-08-13
Active model version: 4.0.0-candidate
Candidate model: Model 5.0 factor architecture (`FACTOR_MODEL_ENABLED`, default off)

> This document describes the **active** 4.x model. Model 5.0 replaces the 70/30
> core score with five separable factor blocks, MA200 trend gates with
> hysteresis, a market-regime overlay and eligibility-class ranking. It is
> implemented and unit-tested but **not enabled**; see section 20 of
> `docs/stock_screener_system_architecture.md` for its full contract, its known
> data gaps, and the validation protocol required before promotion.

## What the output means

`Decision_Score` (also exported as the backward-compatible `Final_Score`) and
`Rating` are deterministic research-ranking heuristics. They are not estimates
of expected return, probability of profit, fair value, or a SEBI-regulated
recommendation. The labels remain useful for preserving the existing workflow,
but the application explicitly exports
`Model_Validation_Status = Research model; point-in-time out-of-sample
validation pending`.

Research can support a variable's economic relevance or an indicator's
definition. It cannot prove this application's exact point grids, 70/30 core
blend, DCF/transcript weights, coverage thresholds, or rating cut-offs. Those
parameters remain **heuristic** until the versioned model produces enough genuinely
out-of-sample observations, including delisted names, benchmark returns,
transaction costs, and no look-ahead data.

## Data-source boundary

- The NSE symbol universe and monthly liquidity category/impact-cost file are
  exchange sources. The impact-cost file is cached and its date, URL and stale
  state are exported.
- Daily OHLCV and company fundamentals come through Yahoo Finance/yfinance,
  which is a convenient free secondary feed without an exchange-data SLA.
  Fundamentals are cached for seven days and can be revised, so they are not a
  historical point-in-time database. Before the configured 16:15
  Asia/Kolkata completion cutoff, a same-day daily bar is excluded; at or after
  the cutoff it may be used. The default is aligned with NSE's official capital-
  market trade-modification cutoff. The same selected bar frame supplies current
  price, returns, indicators, volume and liquidity. Unadjusted close is used for
  actual traded value; split/dividend-adjusted OHLC is used for returns and
  indicators. PE, PB, market capitalization and EV/EBITDA are recomputed from
  that completed close when their raw denominators are available. A normal
  session must match the latest expected completed NSE date; lagging symbols
  are excluded. The exchange holiday list is a versioned, config-hashed
  snapshot and must be updated for ad-hoc circulars and special sessions.
- Price-history depth and technical-cache schema follow the selected model.
  With `FACTOR_MODEL_ENABLED=false`, the active 4.x path remains `6mo` with
  cache contract v6. Model 5.0 selects `2y` and v7 for MA200, 12-1 momentum,
  one-year drawdown, and relative-strength inputs; legacy six-month features
  remain pinned to 126 sessions inside the longer frame. Distinct versions
  prevent cached technical rows from being mixed across the two contracts.
- Transcript discovery starts from NSE corporate filings. Parsed text and
  derived NLP output are cached in Supabase by a separate worker so the daily
  scan performs a bulk lookup rather than per-company document analysis.
- VIGIL is a free secondary aggregation of exchange/regulatory records. Its
  evidence remains shadow-only and requires confirmation against the original
  filing before any future live policy.
- The free application has no reliable point-in-time analyst-consensus and
  estimate-revision history. Earnings-surprise/consensus is therefore absent,
  not silently approximated. News keywords and the FII/DII placeholder do not
  enter the score.

## Model v4 score and decision contract

The scoring, reverse-DCF, and transcript modules are evidence producers. They
may export provisional diagnostics, but only the pure finalizer in
`screener/recommendation.py` is authoritative for the published decision score,
rating, policy gates, and research ranks. Re-running that finalizer on the same
evidence is deterministic and does not let a later enrichment bypass an earlier
coverage, quality, or trend gate.

### Core score and evidence coverage

The core score is fixed rather than volatility-regime dependent; ATR already
has its own technical component and is not counted again by changing weights:

```text
Core_Score = Combined_Score
           = 0.70 * Fundamental_Score + 0.30 * Technical_Score
```

Fundamental coverage is the number of available fields divided by the fields
expected by the selected generic or sector-specific model. Missing fundamental
inputs receive no component points and are named in
`Fundamental_Missing_Fields`. Technical coverage is the share of the total
technical-component point capacity that was observable. The technical score is
confidence-shrunk toward neutral rather than filled with hidden default points:

```text
Technical_Score = 50
                + Technical_Coverage * (Technical_Observed_Score - 50)
```

The default BUY coverage floors are 0.55 fundamental and 0.75 technical. The
default STRONG BUY floors are 0.75 and 0.90. `Coverage_Eligible`, the two
component eligibility flags, coverage fractions, and missing fields/components
are exported. Insufficient BUY coverage caps `Decision_Score` at 59.99; it is
not interpreted as neutral or favorable evidence.

### Symmetric reverse-DCF evidence

The reverse-DCF module never writes a final score, rating, or rank. It estimates
a base-case equity-cash-flow value and uses one value-to-market-cap relationship
instead of stacking correlated threshold bonuses:

```text
DCF_Valuation_Score = 50
                    + 50 * tanh(log(base_case_value / market_cap) / scale)
Score_After_DCF = Core_Score
                  + w_dcf * (DCF_Valuation_Score - 50)
```

The log mapping makes reciprocal valuation gaps symmetric around neutral 50;
finite observations are bounded away from exact 0 and 100. Both favorable and
adverse evidence receive the same configured weight (0.10 by default). A solve
outside the configured growth interval is exported as a censored upper or lower
bound, not falsely reported as an exact endpoint. Only a usable supported-sector
result based on reported positive cash flow is blend-eligible. Estimated cash
flow, missing inputs, unsupported sectors, and failed solves are audit-only with
a neutral score and zero applied weight. Reported non-positive cash flow is not
silently converted to an estimate: it is marked unmodelled/review-required and,
by default, prevents STRONG BUY until a validated normalization model exists.

### Downside-only transcript evidence

A transcript must be fresh and belong to the current reporting cycle to be
score-eligible. Its applied weight decays continuously with age and tapers near
the next reporting-cycle transition. Production v4 then applies it after DCF
as centered, downside-only evidence:

```text
Evidence_Score = Score_After_DCF
                 + w_tx * min(Transcript_Effective_Score - 50, 0)
```

The default `w_tx` is 0.15. Positive management language can be displayed as
context but cannot promote the post-DCF score or rating. Lowered guidance and
high risk remain explicit audit fields rather than being counted twice as a
second numerical cap. A missing, expired, prior-cycle, unavailable, or
unconfigured transcript leaves `Score_After_DCF` unchanged and creates no rank
priority. Because companies are not required to hold calls, missing transcript
evidence does not cap STRONG BUY unless the optional
`REQUIRE_TRANSCRIPT_FOR_STRONG_BUY` policy is deliberately enabled.

### One final decision and four rank views

After evidence blending, the finalizer enumerates every simultaneous gate
failure. BUY failures impose a ceiling of 59.99; STRONG BUY failures impose a
ceiling of 69.99. Coverage, stale or anomalous fundamentals, unavailable
specialized models/regulatory fields, price-versus-MA50, MA50 slope, three-month
return, growth, ADX/+DI/-DI, and technical strength can therefore prevent an
overlay from resurrecting an ineligible recommendation:

```text
Decision_Score = min(Evidence_Score, Decision_Score_Ceiling)
Final_Score = Decision_Score
Rating = STRONG BUY (70+), BUY (60-69.99), HOLD (50-59.99),
         REDUCE (40-49.99), or SELL (<40)
```

The output deliberately retains four questions rather than overloading one
rank:

- `Score_Rank` orders uncapped `Evidence_Score` descending.
- `Recommendation_Rank` orders published rating class first, then
  `Decision_Score`, then evidence.
- `Investment_Rank` orders `Decision_Score` first, then evidence. It is the
  primary report order, and `Rank` is its compatibility alias.
- `Actionable_Rank` puts rows executable for the configured target position
  first, then orders by decision score. It is an execution view only and cannot
  change score, rating, or `Investment_Rank`.

Symbol is the deterministic final tie-break. Transcript availability is not a
rank tier, and the normal v4 research universe is not prefiltered by liquidity.
The output also exports distance-to-gate fields and a
`Decision_Stability_Status` (`CLEAR`, `BORDERLINE`, `POLICY_CAPPED`, or
`DATA_LIMITED`). These diagnostics expose proximity; they do not yet implement
stateful hysteresis. Exact policy boundaries such as ADX 20, positive three-
month return, and score 60/70 therefore remain categorical cliffs until their
bands and persistence are calibrated by walk-forward validation rather than
hand-tuned in production.

## Logic ledger

| Component | Application policy | Evidence assessment |
|---|---|---|
| Fundamental value, profitability and investment | PE/PB, profitability, leverage, growth and sector-relative ranks contribute to the fundamental score; financial firms use dedicated models. | **Concept supported; exact weights heuristic.** Fama and French document value, profitability and investment patterns. Novy-Marx documents gross profitability. Comparing like businesses is economically preferable to applying industrial leverage ratios to banks, but this app's score grid has not been return-validated. |
| Data quality, coverage and anomalies | Fundamental and technical coverage are exported; missing technical evidence shrinks its observed score toward 50, while insufficient required coverage prevents BUY. Extreme PE/profitability/growth observations are flagged and can cap conviction. | **Defensive control.** It avoids turning absent or obviously exceptional data into positive evidence. Thresholds are operational guardrails, not alpha claims. |
| Trend and momentum | MA50 slope, three-month return, MA alignment, MACD, RSI, StochRSI and ADX/+DI/-DI describe trend state; BUY requires a constructive trend by default. | **Concept supported; combination heuristic.** Momentum is documented over intermediate horizons. ADX measures strength, not direction, so the implementation checks +DI versus -DI. Technical patterns can add information but require systematic out-of-sample evaluation. |
| Price-volume demand proxy | Standard 21-session Chaikin Money Flow plus 20-day price return labels accumulation, distribution, mixed, or unavailable. Together with relative volume, that status supplies the scored `VOL` technical component (0-15 points): accumulation can confirm volume, distribution penalizes it, mixed is neutral, and unavailable is omitted with lower coverage. | **Definition supported; predictive use deliberately limited.** This is a scored technical confirmation, not proof of institutional flow. CMF describes price-volume pressure but cannot identify the buyer, and the exact point curve remains heuristic. There is no separate post-score bonus or rating override. |
| Transcript sentiment and guidance | A fresh current-cycle call can contribute up to the configured 15% after DCF; the applied weight decays with age and tapers near the next cycle, while production v4 uses only the centered downside. Missing, prior-cycle, or expired calls are neutral and create no rank priority. | **Information content supported; exact NLP score/15% weight heuristic.** Research finds management tone/guidance can contain information, but optimistic tone can also reflect impression management. Positive language is therefore contextual; only adverse evidence can reduce conviction. |
| Reverse DCF | The module exports market-implied cash-flow/terminal-growth diagnostics and a single smooth log value-to-market score symmetric around 50. The central finalizer blends reliable reported favorable or adverse evidence at the same configured weight (10% by default); estimated, missing, unsupported, or unusable paths are neutral. | **Valuation framework supported; assumptions are scenarios.** Present-value valuation and terminal assumptions are standard, but discount rate, sector growth benchmarks and Yahoo cash-flow data are not forecasts. Output is labelled market-implied/scenario evidence, and the DCF module itself never writes a recommendation. |
| Liquidity and execution | NSE Group I/II/III and mean impact cost for a Rs1 lakh order are primary. A 1% median-turnover participation proxy is used for larger/custom positions or unavailable official impact values. Normal v4 runs do not prefilter the research universe by liquidity. Liquidity changes only `Actionable_Rank`; primary `Rank` remains `Investment_Rank`. | **Official definition for the reference order; extrapolation heuristic.** NSE/SEBI define Group I as at least 80% trading frequency and no more than 1% mean impact cost for a Rs1 lakh order. Build capacity above that size is only a conservative planning proxy, not a market-impact forecast. |
| Exchange/issuer red flags | Credit-default, pledge/encumbrance and exchange-surveillance evidence is cached and shown as shadow counterfactuals. | **Risk relevance supported; automated severity policy not validated.** VIGIL is a convenient free aggregation rather than the primary exchange filing. Nothing changes live score/rating until the underlying NSE/SEBI/issuer evidence is confirmed. |
| News and FII/DII | Headline sentiment is displayed for top rows; FII/DII is logged. | **Experimental/display-only.** Neither is an active score input. The FII/DII implementation is explicitly a placeholder. |
| Versioned outcome log | Each run stores model version and later realized prices. Performance summaries exclude observations from other model versions. | **Necessary but not yet sufficient.** Absolute return averages are monitoring diagnostics; a proper evaluation still needs benchmark-relative, survivorship-free, point-in-time results and costs. |

## Primary and research sources

### Liquidity and market execution

- [NSE: Market Timings](https://www.nseindia.com/static/market-data/market-timings) lists the normal equity-market close, closing session, and 16:15 trade-modification cutoff used by the completed-bar policy.
- [NSE: Impact Cost](https://www.nseindia.com/static/products-services/indices-impact-cost) defines impact cost as an order-size-dependent measure of execution/liquidity.
- [NSE security categorisation circular](https://nsearchives.nseindia.com/content/circulars/cmpt5868.htm) and the [SEBI categorisation annexure](https://www.sebi.gov.in/sebi_data/commondocs/ann4mast_p.pdf) specify the six-month frequency and Rs1 lakh mean-impact-cost tests: Group I requires trading on at least 80% of days and impact cost no greater than 1%.
- [NSE Margin Trading Facility FAQ](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/FAQs%20on%20Margin%20Trading%20Facility_0.pdf) documents the exchange security-category file and Group I eligibility.

### Fundamentals and valuation

- [Fama and French, *A five-factor asset pricing model*](https://www.sciencedirect.com/science/article/pii/S0304405X14002323/pdf) documents value, profitability and investment-related return patterns.
- [Novy-Marx, *The Other Side of Value: The Gross Profitability Premium*](https://oldschoolvalue-files.s3.amazonaws.com/pdf/Novy-Marx_Gross-Profitability-Anomaly_JFE_2013.pdf) documents the relation between profitability and average returns.
- [CFA Institute, *Equity Valuation: Concepts and Basic Tools*](https://rpc.cfainstitute.org/research/foundation/2024/valuation-handbook-2023) describes present-value valuation and the uncertainty in required-return assumptions.
- [Damodaran, *Growth and Terminal Value*](https://www.stern.nyu.edu/~adamodar/pdfiles/ovhds/dam2ed/growthandtermvalue.pdf) explains the sensitivity of DCF value to growth and terminal-value assumptions.

### Technical and volume evidence

- [Jegadeesh and Titman, *Returns to Buying Winners and Selling Losers*](https://www.jstor.org/stable/2328882) documents intermediate-horizon return continuation; it does not validate this application's thresholds.
- [Lo, Mamaysky and Wang, NBER Working Paper 7613](https://www.nber.org/papers/w7613) finds that some systematically recognized technical patterns can provide incremental information while emphasizing the need for objective methods.
- [Fidelity: Average Directional Index](https://www.fidelity.com/viewpoints/active-investor/average-directional-index-adx) explains that ADX measures trend strength and +DI/-DI indicate direction.
- [Fidelity: Chaikin Money Flow](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/cmf) gives the standard CMF construction and its accumulation/distribution interpretation.
- [Lee and Swaminathan, *Price Momentum and Trading Volume*](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00280) shows that volume interacts with momentum; it does not support equating turnover with demand or guaranteed returns.

### Management communication

- [Huang, Teoh and Zhang, *Tone Management*](https://www.hks.harvard.edu/centers/mrcbg/publications/fwp/2015-05) reports that abnormal management tone is associated with future earnings, uncertainty and delayed market reaction.
- [Davis, Ge, Matsumoto and Zhang, *The Effect of Manager-Specific Optimism on the Tone of Earnings Conference Calls*](https://www.sciencedirect.com/science/article/abs/pii/S0378426611002901) supports studying call tone while showing that manager style matters.
- [*Managerial Ability and Stock Price Crash Risk*](https://doi.org/10.1007/s10551-019-04326-1) is evidence that optimistic disclosure can coexist with impression-management/crash-risk concerns.
- [*A Catering Theory of Earnings Guidance*](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/catering-theory-of-earnings-guidance-empirical-evidence-and-stock-market-implications/78F476FCE3B34CD72257F526A7A754EF) cautions that guidance decisions can respond to market incentives.

## Validation protocol before calling the model successful

1. Freeze each material logic change under a new `MODEL_VERSION`; never mix its
   outcomes with older versions.
2. Save the complete daily eligible universe and inputs as known on that date,
   including unavailable data and later delistings. Do not rebuild history with
   today's constituents or restated fundamentals.
3. Measure 1-, 3-, 6- and 12-month total returns against Nifty broad-market and
   size-appropriate benchmarks. Include plausible entry slippage, impact cost,
   brokerage, taxes and multi-day builds.
4. Compare rating buckets and deciles for monotonicity, drawdown, hit rate,
   turnover and capacity. Report confidence intervals; do not optimize on one
   period and call the same period a test.
5. Use a walk-forward holdout. Promote a heuristic to a claimed predictive
   rule only after it survives multiple market regimes and remains useful after
   costs.

Until those conditions are met, the application is an auditable research
screener, not a proven return-generation model.

### Additional conditions specific to Model 5.0

6. **Point-in-time fundamentals are the blocking dependency.**
   `screener/statements.py` derives quality and growth evidence from the annual
   statements Yahoo publishes *today*. It makes no attempt to reconstruct what
   was knowable on a past date, so it satisfies condition 2 for a forward screen
   only. A look-ahead-free historical backtest of the factor blocks requires a
   point-in-time fundamentals source that this repository does not have. Scope
   that before scheduling the walk-forward study.
7. **Model 5.0 ratings are cross-sectional, not absolute.** The published score
   is the percentile of the weighted block blend, so roughly 40% of any universe
   is labelled REDUCE or SELL by construction. Bucket monotonicity in condition 4
   must therefore be measured against the same universe definition used in
   production, and the model is intended for full-universe runs rather than
   short watchlists.
8. **Test the grid, not the winner.** Run the pre-declared A-E model grid
   (4.x baseline; factorised 70/30; 60/40 with MA200 gate; proposed without the
   MA200 gate; proposed with the regime overlay) and report all five. Selecting
   the best of many variants on one sample and calling that sample a holdout is
   the specific failure mode this protocol exists to prevent.
9. **Require a substantially complete statement cross-section.** The isolated
   candidate workflow refuses a Model 5.0 comparison below 95% statement
   coverage of the full candidate universe. It accumulates bounded backfill
   tranches in a branch-scoped candidate cache, optionally seeds from a prior
   candidate artifact, and checkpoints a successful tranche before comparison.
   This prevents a partial, order-dependent cross-section from being treated as
   validation evidence; it does not solve the point-in-time limitation in
   condition 6.

The candidate job may use `SUPABASE_URL` and the service-role secret to bulk-read
the same cached transcript evidence as production. `SUPABASE_READ_ONLY=True`
rejects non-GET requests: validation does not publish to Supabase, and neither
the secret nor any other credential is included in its cache or artifacts.
