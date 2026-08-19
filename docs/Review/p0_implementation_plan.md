# P0 Implementation Plan — Point-in-Time Validation of Model 5.0

- **Status:** active build plan
- **Scope:** the P0 block of `docs/Review/model_review.md`, as expanded in `docs/Review/p0.md`
- **Branch:** `feat/p0-point-in-time-validation`
- **Decisions:** hybrid data path, monthly rebalance, window 2022-07 → present
- **Last reviewed:** 2026-08-19

> **What P0 is for.** Not to show that Model 5.0 produced attractive historical
> numbers. To make it difficult for the model to cheat accidentally. Every item
> below exists to remove one specific way a backtest can flatter itself.

---

## 1. Review triage — what is already built

`docs/Review/model_review.md` was written against the architecture description,
not the code. Five of its recommendations are already implemented. They are
recorded here so nobody spends a sprint rebuilding them.

| Review item | Status | Evidence |
| --- | --- | --- |
| §A volatility-adjusted, skip-month momentum | **Already implemented** | `RiskAdj_Momentum_12_1` (w=0.30), `RiskAdj_Momentum_6_1` (w=0.25) in `screener/factors.py`; `TechnicalEnhancer.skip_month_return` in `screener/market_data.py` |
| P2 sector-neutral percentiles | **Already implemented** | `FACTOR_SECTOR_NEUTRAL=True`, `FACTOR_MIN_SECTOR_PEERS=8` |
| P2 winsorize inputs before ranking | **Already implemented** | `FACTOR_WINSOR_LOWER_PCT=0.05`, `FACTOR_WINSOR_UPPER_PCT=0.95` |
| P2 earnings stability + accrual quality | **Already implemented** | `Earnings_Stability`, `Accruals_To_Assets` in `QUALITY_GENERIC` |
| §4 add a true reverse DCF solving for implied growth | **Already implemented** | `ReverseDCFModel.analyze_row` solves `fcf_solve` for the growth that equates DCF value to market cap |

§4 is half-right and the surviving half matters: the genuine implied-growth solve
*and* a fixed-assumption base case both live under the name "reverse DCF", and it
is the fixed-assumption branch that produces the published upside number. The
rename to `Scenario_DCF` is justified. "Add the missing reverse DCF" is not.

### 1.1 Criticisms confirmed valid in code

These are real and stay on the backlog:

- Single fixed discount rate (11%) and terminal growth (4%) for every company
  regardless of leverage, size or cyclicality — `REVERSE_DCF_DISCOUNT_RATE`.
- Latest-year FCF used unnormalized.
- No valuation-conflict gate on STRONG BUY. Existing gates cover quality,
  growth, momentum, MA50/MA200, regime and reported-negative-FCF — nothing
  constrains a severely expensive valuation.
- No point-in-time predictive validation. `screener/statements.py` says so in
  its own module docstring.
- Rating thresholds are policy labels, not calibrated probabilities.

---

## 2. Two structural blockers the P0 doc does not mention

**The statement cache cannot reconstruct a historical cross-section.**
`derive_statement_factors` collapses the multi-year statement panel into
latest-period scalars (`ROIC`, `Revenue_CAGR_3Y`, …) and only those scalars are
persisted. The raw panel is discarded. A historical cross-section therefore
cannot be derived from the existing cache at any date — P0 needs a new
raw-panel store, not a re-read of `statement_cache.csv`.

**The existing `BacktestEngine` is a forward shadow tracker, not a backtest.**
It enters at the same close that generated the signal — exactly what `p0.md` §4
forbids — and records no realized holding period, so a gap in the daily cadence
silently stretches a "30-day" return into whatever the gap was. It is kept
as-is for continuity and superseded by the new engine, which is separate.

---

## 3. The data foundation exists and is free

Both review documents implicitly assume a paid point-in-time vendor is required.
It is not. The `nse` package already in `requirements.txt` carries the archive.
Verified live on 2026-08-19:

| Need | Source | Verified |
| --- | --- | --- |
| Statement publication timestamp | `nse.financial_results()` → `filingDate` (to the minute), `broadCastDate`, `exchdisstime` | ~11–14k filings/year back to **2020**, 1,700–2,100 symbols/year |
| Permanent identifier | same call → `isin` | present on every row |
| As-filed (original, non-restated) numbers | same call → `xbrl` document link | present on 100% of sampled rows |
| Point-in-time universe incl. delistings | `nse.equityBhavcopy(date)` | works for arbitrary past dates; 2,211 rows (2022-06-15) vs 3,483 (2026-08-11) |
| Point-in-time OHLC for next-session fills | same bhavcopy | old format pre-2024-07-08, UDIFF format after |
| Benchmark history | `nse.fetch_historical_index_data()` | available |
| Corporate actions | `nse.actions()` | available |

Two properties make this the right spine:

1. `financial_results` filters on **filing date, not period**. A 2024 window
   returns periods ending as far back as 2020-03-31 — late filings included.
   That is precisely the semantics `data_available_from` requires.
2. The bhavcopy for date *t* **is** the tradable universe on date *t*. Symbols
   later delisted are present; today's survivors are not privileged.

### 3.1 Findings from the live archive

Two things surfaced only by ingesting real files, and both would have corrupted
the run silently.

**ISIN is not a permanent identifier in India.** A face-value change — a split or
bonus issue — is assigned a new ISIN that keeps only the nine-character
issuer-security core. `BAJFINANCE` went `INE296A01024` → `INE296A01032`;
`KOTAKBANK`, `DRREDDY`, `CANBK`, `COFORGE`, `PERSISTENT`, `SHRIRAMFIN` and `MCX`
all did the same. **150 of 226 apparent disappearances between 2024-01 and
2026-08 were face-value changes, not delistings** — 66%. Keyed on the raw ISIN,
those healthy large-caps would each have been marked delisted and exited at
whatever `DelistingPolicy` assumes, fabricating losses in the most liquid part of
the universe. Fixed by bridging ISINs into a `Security_ID` chain; the true
delisting rate over the window is **3.4%, not the naive 10.7%**.

**ETFs sit in the `EQ` series.** `LICMFGOLD`, `NIF100IETF`, `IVZINNIFTY` and
`IVZINGOLD` came through the equity filter. They are not stock-selection
candidates and will distort sector-neutral percentiles and the equal-weight
benchmark. *Open item:* exclude them at universe-build time via `nse.listEtf()`.
The bhavcopy archive itself stays faithful to what traded — filtering belongs in
the universe layer, not the raw store.

### 3.2 The constraint that shapes everything

yfinance holds **exactly four annual periods** (confirmed: TCS returns
FY2023–FY2026) and publishes **no** statement dates. `Revenue_CAGR_3Y` needs
four years of revenue, so a 2024 rebalance needs FY2021 — which yfinance no
longer carries.

**yfinance cannot support a retrospective test at any depth.** A real historical
run of the full factor set requires the NSE XBRL panel. This is why the build is
split into a shared engine and a pluggable fundamentals provider.

---

## 4. Build sequence

The engine is common to every path and is built first. The fundamentals provider
is the swappable part.

### Phase A — spine (no fundamentals required)

| # | Component | Module | P0 item | Status |
| --- | --- | --- | --- | --- |
| A1 | Trading calendar from bhavcopy availability | `backtest/calendar.py` | 4 | **done** |
| A2 | Bhavcopy ingestion, both formats, cached + resumable | `backtest/bhavcopy.py` | 3 | **done** |
| A3 | `Security_ID` master: listing, delisting, renames, splits, suspensions | `backtest/security_master.py` | 3 | **done** |
| A3b | Corporate-action adjustment (**added**, see below) | `backtest/corporate_actions.py` | 4 | **done** |
| A4 | Next-session execution (signal on close *t*, fill at open *t+1*) | `backtest/execution.py` | 4 | |
| A5 | Forward returns at 1/3/6/12 months | `backtest/forward_returns.py` | 4 | |
| A6 | Costs, turnover, slippage, liquidity capacity | `backtest/costs.py` | 5 | |
| A7 | Rank IC, decile buckets, portfolio metrics | `backtest/metrics.py` | 4 | |
| A8 | Walk-forward orchestration | `backtest/runner.py` | 4 | |

**A3b was not in the original plan and is not optional.** Bhavcopy prices are raw
and `Prev_Close` is *not* exchange-adjusted — verified on NARMADA's 2026-07-31
split, where the close moved 36.19 → 17.02 while `Prev_Close` still read 36.19.
Without adjustment every split is a fabricated ~50% loss and the momentum block
scores corporate actions instead of performance. Splits, bonuses and dividends are
adjusted exactly from `nse.actions()`; rights issues, demergers and buybacks are
flagged and excluded rather than approximated.

**Phase A milestone — a genuine retrospective test with zero fundamentals.**
The momentum and risk blocks need only price history, and the equal-weight
eligible-universe benchmark needs only the universe. Both come from bhavcopy.
This runs the full walk-forward on 2022-07 → present and answers `p0.md`
benchmark E — *is Model 5.0 primarily a momentum strategy?* — before any XBRL
work lands. It also proves the engine end-to-end on real data.

### Phase B — point-in-time fundamentals

| # | Component | Module | P0 item |
| --- | --- | --- | --- |
| B1 | Filing-metadata ingestion, ISIN-keyed, filing timestamps | `backtest/filings.py` | 1 |
| B2 | Statement versioning: original vs restated, `supersedes_version` | `backtest/filings.py` | 2 |
| B3 | XBRL parsing into a raw multi-year panel | `backtest/xbrl.py` | 1 |
| B4 | Point-in-time resolver: newest filing where `data_available_from <= t` | `backtest/pit.py` | 1, 2 |
| B5 | Pluggable provider interface; historical panel → factor inputs | `backtest/providers.py` | 1 |

Conservative availability rule, per `p0.md`: a filing is usable from the **next
completed trading session** after `broadCastDate`, regardless of whether it
landed before or after the close.

### Phase C — validation

| # | Component | P0 item |
| --- | --- | --- |
| C1 | Benchmark + ablation matrix: Nifty 500 TRI, equal-weight universe, Model 4.x, quality-only, growth-only, value-only, momentum-only, simple 50/50 QM, Model 5.0 | 7 |
| C2 | Freeze specification: config hash, git SHA, dataset + calendar + engine versions | 6 |
| C3 | Untouched final-window run and report | 6 |
| C4 | Live shadow tracking, replacing the current `BacktestEngine` | — |

---

## 5. Test configuration

```
Window:            2022-07-01 → present
Rebalance:         monthly (~48 dates)
Horizons:          1 / 3 / 6 / 12 months, reporting 3M and 6M first
Signal:            completed close on rebalance date t
Entry:             open of t+1
Exit:              open of t+1+horizon
Weights (frozen):  Quality 35 / Growth 20 / Value 15 / Momentum 25 / Risk 5
Portfolios:        top 10, top 20, top 50, top decile, BUY+STRONG BUY only
Capacity probes:   Rs 10L, 50L, 1Cr, 5Cr, 10Cr
```

Weights stay frozen for the first pass. Expanding-window recalibration is a
separate later experiment, not part of this validation.

### 5.1 Residual biases, stated up front

The final report must carry these; they do not disappear because the engine is
correct.

- **Restatement bias** is removed only where XBRL as-filed values are parsed
  (B3). Any period falling back to a provider's current values inherits it.
- **Delisting return policy** is a modelling choice, not an observation.
  Acquisitions use consideration received; distress applies recovery value and
  does **not** carry the last quoted price forward.
- **Period count.** Monthly rebalancing over ~4 years is ~48 observations. That
  is enough to judge cross-sectional rank IC and its stability; it is *not*
  enough to make a confident claim about regime robustness across a full cycle.
- **Cost schedule.** Historical charge changes are modelled with effective dates
  where known; unknown periods use the nearest known schedule and are flagged.

---

## 6. Acceptance criteria

From `p0.md`. No single threshold. Model 5.0 passes P0 when it clears all four
groups, and the report states plainly which it fails.

**Predictive** — positive average *and* median rank IC; positive IC in a
majority of periods; top bucket beats the eligible-universe average; reasonably
monotonic buckets; not dependent on one sector or one year.

**Portfolio** — positive excess return after costs; better risk-adjusted return
than the simple benchmarks; acceptable max drawdown; sustainable turnover;
sufficient capacity.

**Robustness** — survives different start dates, cost assumptions, and top-20 /
top-50 / top-decile constructions; small weight perturbations do not destroy it;
persists across regimes; beats or complements simple 50/50 quality-momentum.

**Integrity** — point-in-time fundamentals; historical universe; explicit
delisting treatment; no same-close execution; frozen specification;
reproducible run manifest.

> If Model 5.0 performs well only with current survivors, latest restated
> statements, same-close execution and zero cost, it has established nothing.

---

## 7. Out of scope here

P1 (valuation interpretation), P2 (remaining factor construction) and P3
(recommendation calibration) are deliberately excluded. P3 in particular
*cannot* be done before P0 finishes — calibrating labels requires the historical
outcome distribution P0 produces. The `Scenario_DCF` rename and the
valuation-conflict gate from P1 are independent of P0 and can proceed in
parallel on their own branch.
