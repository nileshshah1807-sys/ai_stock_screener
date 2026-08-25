# P2 pre-registration: do the relative-strength gates earn their place?

Written **before** the grid was run, for the same reason as P1: a decision rule
chosen after seeing the winner is not a decision rule. Condition 8 of the
validation protocol in `docs/model_methodology.md`.

Author: research session, 2026-08-25.
Baseline commit: `a0f53c7`. Follows `p1_growth_reweight_preregistration.md`.

## The observation that motivates it

Profiling the 2026-08-24 production run, the STRONG BUY cohort and the top 20
by `Research_Score` are near-identical on every factor except one:

| | STRONG BUY (n=40) | Top 20 by score |
|---|---|---|
| Momentum percentile | 93.5 | 92.9 |
| Quality percentile | 85.2 | 87.5 |
| Growth percentile | 82.7 | 86.1 |
| **Value percentile** | **26.7** | **96.0** |
| 6M return | +59.9% | +58.1% |
| Median market cap | Rs 16,963 Cr | Rs 1,802 Cr |

Only 5 of the top 20 by score are rated STRONG BUY.

The gates that plausibly cause this are the relative-strength family, because a
name that has already risen ~60% in six months is mechanically no longer cheap:

* `BUY_MIN_RS_6M = 0.0` — 6M market relative strength must be positive (BUY)
* `STRONG_BUY_MIN_RS_12M = 0.0` — 12M relative strength must be positive
* `STRONG_BUY_MIN_MOMENTUM_PCT = 70.0` — momentum percentile floor
* `REGIME_NEUTRAL_MIN_MOMENTUM_PCT_FOR_STRONG_BUY = 85.0` — regime floor

This matters because `value_only` is the only block positive in all four
windows (+29.26 / +45.32 / +32.59 / +23.80) while `momentum_only` is the least
reliable (−21.31 in FORWARD). If the rating filter systematically excludes the
value factor, it is trading the best block for the worst one.

**Hypothesis.** Keeping the risk-control gates but dropping or softening the
relative-strength gates improves gate-ordered selection, and restores value
exposure to the eligible cohort.

## What is deliberately NOT touched

These stay at production values in every variant. They are the gates' actual
risk-control job, and this experiment is not an argument for removing them:

* `BUY_MA200_TOLERANCE = 0.98` — price within the MA200 band
* `BUY_MIN_MA200_SLOPE_PCT = 0.0` — MA200 not falling
* `BREAKDOWN_CONFIRM_SESSIONS = 10` — confirmed breakdown below MA200
* `STRONG_BUY_REQUIRE_MA50_ABOVE_MA200 = True` — trend structure
* `REGIME_RISK_OFF_DISABLES_STRONG_BUY = True` — no STRONG BUY in a risk-off market
* `REGIME_RISK_OFF_MIN_MOMENTUM_PCT = 90.0` — risk-off BUY floor
* `BUY_MIN_QUALITY_PCT`, `STRONG_BUY_MIN_QUALITY_PCT`, `STRONG_BUY_MIN_GROWTH_PCT`

## Pre-declared ladder

Progressive removal of relative-strength requirements, one family at a time.

| Variant | 6M RS (BUY) | 12M RS (SB) | Momentum pct floor (SB) | Regime neutral floor |
|---|---|---|---|---|
| **R0** baseline = `model_5_gated` | required | required | 70 | 85 |
| **R1** drop 6M market RS | **off** | required | 70 | 85 |
| **R2** R1 + drop 12M RS | **off** | **off** | 70 | 85 |
| **R3** R2 + drop momentum floors | **off** | **off** | **0** | **0** |

R3 is "risk control only": MA200 band, MA200 slope, confirmed breakdown, the
bullish stack, risk-off regime, and the quality/growth floors — no
relative-strength requirement at all.

## Expected effect size, declared up front

Unlike P1, this can be large. The gates change *which names are eligible*, not
a 20%-weighted block input. P1's ladder moved the top-20 by 1-7 names; this can
move it wholesale. A multi-point CAGR difference here is therefore **not**
automatically noise — but it must still be consistent across windows and
ordered across the ladder to count.

Directional prior, stated before running: R1-R3 improve on R0 in the windows
where value works (MAIN, BS_ERA, FORWARD) and are neutral-to-worse in BEAR,
where relative strength is the only thing that helped. Confidence this clears
the full bar: **~30%**.

## Windows

Identical to P1 and to the published 5.1 table: BEAR 2018-11→2020-06,
MAIN 2020-07→2025-01, BS_ERA 2023-07→2025-01, FORWARD 2025-02→2025-10.
`--with-fundamentals --horizons 1,3,6 --min-history 200`.

**BEAR carries the P1 caveat**: quality coverage 0.08 and growth coverage 0.03
there, so `STRONG_BUY_MIN_GROWTH_PCT` and the quality floors behave differently
from production. BEAR results on gate variants are read as indicative only.

None of these windows is a holdout.

## Decision rule, fixed in advance

A variant is promoted **only if all four hold**:

1. Beats R0 on net CAGR versus the equal-weight eligible universe in **at least
   3 of the 4 windows**.
2. Does **not** degrade FORWARD by more than 2 points versus R0.
3. Beats R0 on **maximum drawdown** in BEAR, or degrades it by less than 3
   points. The gates exist for downside protection; a variant that buys return
   by removing that protection has not improved them, it has removed them.
4. The ladder response is **ordered** — an isolated R2 win with R1 and R3
   losing is noise.

**Mixed result => nothing changes.** The gates ship as they are.

**Even on a clean pass**, promotion is: record here → ship behind the existing
`BUY_MIN_RS_6M` / `STRONG_BUY_MIN_RS_12M` / `STRONG_BUY_MIN_MOMENTUM_PCT`
config knobs at production defaults → wait for live evidence in
`backtest_history.csv` → flip defaults only when that agrees.

## Secondary measurement, not a promotion criterion

For each variant, the **median value percentile of the eligible cohort**. This
tests the *mechanism* rather than the outcome: if softening RS gates does not
raise value exposure, the diagnosis in this document is wrong regardless of
what the CAGR column does. Recorded either way.

## What this cannot establish

Everything in P1's list, plus:

* A top-20-always backtest cannot measure the gates' abstention value —
  publishing no BUY at all and the reader holding cash. That is the gates' real
  protective function and it is invisible here. **This experiment can therefore
  only ever argue about gates-as-selection, never gates-as-risk-switch.**
* The archive has no sector map, so production's 6M *sector* relative-strength
  gate is absent from every variant including the baseline.

---

# Result, recorded 2026-08-25

Run: `tools.run_p0_backtest --with-fundamentals --gate-relaxation-grid`, four
windows, results in `reports_advanced/backtest/p2_{bear,main,bs_era,forward}.json`.

## Verdict: NOT PROMOTED. The stated hypothesis is refuted, and the variant
## that did win confounds two changes.

## Net CAGR minus the equal-weight eligible universe

| Strategy | BEAR | MAIN | BS_ERA | FORWARD |
|---|---|---|---|---|
| R0 `model_5_gated` (production) | +23.86 | +22.16 | +17.98 | −10.09 |
| R1 no 6M RS | +23.86 | +22.05 | +19.15 | −10.09 |
| R2 no RS at all | +23.86 | +21.52 | +17.48 | −10.09 |
| R3 risk-control only | +23.86 | +23.91 | +23.42 | **−0.78** |
| *(ungated `model_5`, reference)* | +23.86 | +23.99 | +25.25 | −7.02 |

## Risk metrics

| Max drawdown % | BEAR | MAIN | BS_ERA | FORWARD |
|---|---|---|---|---|
| R0 | −17.53 | −15.61 | −10.76 | −7.62 |
| R1 | −17.53 | −15.61 | −10.76 | −7.62 |
| R2 | −17.53 | −15.61 | −10.76 | −7.62 |
| R3 | −17.53 | −15.61 | −11.51 | **−5.27** |

| Sharpe | BEAR | MAIN | BS_ERA | FORWARD |
|---|---|---|---|---|
| R0 | 0.523 | 2.028 | 1.931 | 1.212 |
| R3 | 0.523 | 2.061 | 2.038 | **1.625** |

## Against the pre-registered rule

| Criterion | R1 | R2 | R3 |
|---|---|---|---|
| 1. beats R0 in ≥3 of 4 windows | 1/4 FAIL | 0/4 FAIL | 3/4 **PASS** |
| 2. FORWARD not worse by >2pp | PASS | PASS | **PASS** (+9.31) |
| 3. BEAR drawdown not worse by >3pp | PASS (0.00) | PASS (0.00) | **PASS** (0.00) |
| 4. ordered ladder response | — | — | **AMBIGUOUS** |

## The stated hypothesis is refuted

The document above predicted that the **relative-strength** gates
(`BUY_MIN_RS_6M`, `STRONG_BUY_MIN_RS_12M`) were stripping value names out of
the eligible cohort. R1 and R2 remove exactly those, and they change almost
nothing: R1 is +1.17 in one window and −0.11 in another, R2 is negative in two
of three. **Both are indistinguishable from the baseline.**

Every bit of R3's advantage therefore comes from the one thing R1 and R2 did
not touch: `STRONG_BUY_MIN_MOMENTUM_PCT` 70 → 0 and
`REGIME_NEUTRAL_MIN_MOMENTUM_PCT_FOR_STRONG_BUY` 85 → 0.

## Why R3 is not promotable as it stands

R3 changes **four** thresholds at once. Its result is consistent with "the
momentum percentile floors are the expensive gate", but the run cannot
demonstrate that, because no variant isolates the floors from the RS gates.
Promoting R3 would be promoting the best-performing member of a grid without
knowing which of its four changes produced the effect — the exact failure mode
condition 8 exists to prevent.

A second signal argues for caution. Raw 3-month rank IC:

| | BEAR | MAIN | BS_ERA | FORWARD |
|---|---|---|---|---|
| R0 | 0.1468 | 0.0745 | 0.0927 | 0.0657 |
| R3 | 0.1468 | 0.0732 | 0.0891 | 0.0676 |

R3's ranking quality is marginally **worse** in MAIN and BS_ERA while its CAGR
is better. As in P1, that pattern points at top-20 composition rather than a
better ordering — though here the CAGR magnitude (+9.31 in FORWARD) is far too
large to dismiss as composition alone, and Sharpe improves in every window.

BEAR is identical across all four variants, the same coverage artifact recorded
in P1: quality coverage 0.08 and growth coverage 0.03 there.

## Declared follow-up: R4, a decomposition, not a new hypothesis

Declared **before** running, for the same reason as everything else here.

**R4 = momentum floors off, relative-strength gates ON.**
`STRONG_BUY_MIN_MOMENTUM_PCT = 0`,
`REGIME_NEUTRAL_MIN_MOMENTUM_PCT_FOR_STRONG_BUY = 0`, and
`BUY_MIN_RS_6M` / `STRONG_BUY_MIN_RS_12M` left at production values.

This is not a search for a better variant. It has one job: attribute R3's
result. Two outcomes, both declared now:

* **R4 ≈ R3** — the momentum percentile floors are the expensive gate and the
  RS gates are irrelevant. The finding is then about the floors specifically,
  and R4 (a two-threshold change) becomes the candidate rather than R3.
* **R4 ≈ R0** — the floors are not sufficient either, R3's advantage requires
  the combination, and the result stays unexplained. Nothing is promoted.

Either way, promotion still requires the full path recorded above: ship behind
the existing config knobs at production defaults, then wait for live evidence
in `backtest_history.csv`. No default changes on this run.

---

# R4 decomposition result, recorded 2026-08-25

## Declared outcome 1 fired: R4 ≈ R3.

The momentum percentile floors are the expensive gate. The relative-strength
gates are inert.

| Net CAGR vs universe (pp) | BEAR | MAIN | BS_ERA | FORWARD |
|---|---|---|---|---|
| R0 production gates | +23.86 | +22.05 | +17.98 | −10.24 |
| R1 no 6M RS | +23.86 | +21.93 | +19.15 | −10.24 |
| R2 no RS at all | +23.86 | +21.41 | +17.48 | −10.24 |
| R3 all four off | +23.86 | +23.79 | +23.42 | −0.78 |
| **R4 momentum floors only** | +23.86 | **+23.96** | +23.07 | **−2.09** |
| *(ungated `model_5`)* | +23.86 | +24.12 | +25.25 | −7.02 |

Two thresholds reproduce what four did:
`STRONG_BUY_MIN_MOMENTUM_PCT` 70 → 0 and
`REGIME_NEUTRAL_MIN_MOMENTUM_PCT_FOR_STRONG_BUY` 85 → 0.

## R4 dominates R3 on the diagnostic that mattered

| Rank IC 3M | BEAR | MAIN | BS_ERA | FORWARD |
|---|---|---|---|---|
| R0 | 0.1468 | 0.0745 | 0.0927 | 0.0657 |
| R3 | 0.1468 | 0.0732 | 0.0891 | 0.0676 |
| **R4** | 0.1468 | **0.0745** | **0.0926** | 0.0658 |

R3 degraded ranking quality while raising CAGR — the composition-luck signature.
R4 preserves R0's rank IC to four decimals *and* captures the return, which is
the pattern a real effect produces rather than a lucky top-20.

| Sharpe | MAIN | BS_ERA | FORWARD |
|---|---|---|---|
| R0 | 2.024 | 1.931 | 1.212 |
| R3 | 2.056 | 2.038 | 1.625 |
| **R4** | **2.067** | **2.074** | 1.601 |

| Max drawdown % | BEAR | MAIN | BS_ERA | FORWARD |
|---|---|---|---|---|
| R0 | −17.53 | −15.61 | −10.76 | −7.62 |
| **R4** | −17.53 | −15.61 | −11.51 | **−5.32** |

## Against the pre-registered rule

| Criterion | R4 |
|---|---|
| 1. beats R0 in ≥3 of 4 windows | 3/4 (BEAR tied) **PASS** |
| 2. FORWARD not worse by >2pp | **PASS** (+8.15) |
| 3. BEAR drawdown not worse by >3pp | **PASS** (0.00, identical) |
| 4. ordered ladder response | **PASS, with mechanism**: R1≈R2≈R0 (RS gates inert), R3≈R4 (floors are the driver). Not an isolated point — an attributed one. |

## Why this is mechanically coherent, not just a passing grid

A momentum *percentile* floor is a **cross-sectional** measure. In a falling
market the top 30% by momentum is still the top 30%, so the floor keeps
clearing and provides no absolute downside protection. §8.3's own simulation
showed exactly this: uncapped, a crash publishes the same rating distribution
as a bull market, and what prevents that is the *absolute* gates.

R4 keeps every absolute gate: `BUY_MA200_TOLERANCE`, `BUY_MIN_MA200_SLOPE_PCT`,
`BREAKDOWN_CONFIRM_SESSIONS`, `STRONG_BUY_REQUIRE_MA50_ABOVE_MA200`,
`REGIME_RISK_OFF_DISABLES_STRONG_BUY`, and both RS gates. In a genuine RISK_OFF
regime STRONG BUY remains fully disabled.

So R4 removes a gate that costs return and buys no absolute protection, while
leaving the gates that do buy it untouched.

## Estimated production impact, 2026-08-24 run (NEUTRAL regime)

| | today | under R4 |
|---|---|---|
| STRONG BUY count | 40 (1.7%) | **69 (2.9%)** |

The 29 promoted names: median score 88.4, quality percentile 87.0, momentum
percentile 72.2, 6M return +19.1%, median market cap **Rs 31,511 Cr**. Highest
scoring among them are CORDSCABLE (99.7, value P96), JAYNECOIND (99.7, P93),
KMSUGAR (98.7, P98), NATIONALUM (98.4, P95), SAIL (96.4, P91), NMDC (94.8, P90).

These are large, cheap, high-quality names that trend without being top-decile
momentum. The change does not open the list to micro-caps: median market cap of
the promoted set is 17x that of the current top-20-by-score.

**LUPIN would still not be STRONG BUY** under R4. It continues to fail
`price below MA200 tolerance band`, `6M market relative strength`,
`6M sector relative strength`, and `price/MA50/MA200 not stacked bullishly`.
The gates that address the motivating case are untouched.

## Status: PROMOTED to production 2026-08-25, on explicit authorization.

Recommendation policy 5.1.0 -> **5.2.0**. `MODEL_VERSION` stays 5.1.0: the
factor score and `Investment_Rank` are untouched; only the published rating
changes. The version bump exists so `backtest_history.csv` can separate
pre- and post-change outcomes, which is the whole point of shipping it.

**Shipped with the caveats below unresolved, not with them answered.** The
promotion path recorded here originally called for waiting on live evidence
before flipping defaults; that step was waived deliberately by the project owner
so the live evidence could start accumulating. Everything in the "reasons to
hold" list still applies and should be read as an open risk, not a closed one.

**A correction recorded during promotion.** The CAGR figures above come from
strategies that rank `Research_Score - Eligibility_Class * 1000` --
eligibility-first. Production sets `RANK_BY_ELIGIBILITY_CLASS=false` and ranks on
`Research_Score` alone, so **R4's measured CAGR advantage does not transfer to
production's ranking**; in production this change relabels and nothing more.
Ranking on score alone remains ahead of eligibility-first ranking on rank IC in
all three informative windows (0.0778/0.1006/0.0691 against 0.0745/0.0926/0.0658)
and on CAGR in two of three, so `RANK_BY_ELIGIBILITY_CLASS` stays `false` and was
not part of this promotion.

### Original status at time of the run: NOT PROMOTED

The promotion path declared before the run stands and has not been shortened:

1. Recorded here. **Done.**
2. Ship behind the existing `STRONG_BUY_MIN_MOMENTUM_PCT` and
   `REGIME_NEUTRAL_MIN_MOMENTUM_PCT_FOR_STRONG_BUY` knobs **at production
   defaults (70 / 85)**. No default changes on this run.
3. Wait for live evidence in `backtest_history.csv`, accumulating on every
   scheduled run since 5.1 went live — the only untouched data this project owns.
4. Flip the defaults only when that live evidence agrees.

Reasons to hold despite a clean pass:

* **All four windows have been examined.** R4 is fitted to everything visible,
  exactly like the 5.1 weights that then lost FORWARD by 8.1 points.
* **BEAR is uninformative** — identical across all five variants, the quality
  0.08 / growth 0.03 coverage artifact recorded in P1. Three informative
  windows, not four.
* **The abstention value is unmeasurable here.** A top-20-always backtest
  cannot see the cost of publishing 69 STRONG BUYs instead of 40 into a market
  that then falls. That is the one risk this experiment cannot price, and it is
  the risk the gate was written for.
