# P3 pre-registration: does an entry-timing score earn a place in the ranking?

Written **before** the grid was run, for the same reason as P1 and P2: a decision
rule chosen after seeing the winner is not a decision rule. Condition 8 of the
validation protocol in `docs/model_methodology.md`.

Author: research session, 2026-09-19. Branch `feat/stage-timing-rank`, from
`main` at `634695f`. Follows `p2_relative_strength_gate_preregistration.md`.

## The observation that motivates it

`Investment_Rank` orders on `Research_Score` alone. Every trend input that score
reads looks back six to twelve months, so a stock that has already made its move
keeps passing them for months while it tops out. On the 2026-08-24 production
run VENUSREM was ranked #1 at 100.0 / BUY:

| | VENUSREM, 2026-08-24 |
|---|---|
| 6M / 12M return | +120% / +251% |
| Price vs MA200 | +56% |
| Price vs MA50 | −1.2% |
| RS vs market, 6M / 12M | +120 / +247 |

It then fell 13% in a month while still ranked first. The readers of the list
take rank 1 as "buy first". The rank carries no view on *where in its cycle* a
name is, only on how strong its evidence has been.

**Hypothesis.** Blending a stage/relative-strength timing score into the rank
improves forward returns of the top of the list, by moving fresh Stage 2
advances up and extended or topping names down, without costing the research
score's ranking quality.

The contrary prior is recorded in this repo. `p0_implementation_plan.md` found
eligibility-first ranking cost 5-16 CAGR points wherever the gates bound, and P2
found the momentum percentile floors cost return. Trend conditions used as
*selection* inputs have lost here before. The timing score differs in kind -- it
measures cycle position, not strength -- but that is an argument for testing it,
not for assuming it.

## Definitions, fixed before the run

All in `screener/stage.py`; the backtest calls the same functions production
does.

**Stage** (daily MA50/MA150/MA200; "rising" = above its value 21 sessions ago):

| Stage | Rule, first match wins |
|---|---|
| Stage 2 | close > MA50 > MA150 > MA200, MA200 rising |
| Stage 4 | close < MA200, MA200 falling, MA150 below MA200 or falling |
| S2 Candidate | close above MA150 and MA200, MA150 rising |
| Stage 3 | close below MA150 while the long averages are still rising or stacked, or below a falling MA200 before MA150 has rolled over |
| Stage 1 | anything else |

**RS rating.** `0.4·R63 + 0.2·R126 + 0.2·R189 + 0.2·R252`, cross-sectional
percentile on 1-99. `RS_Rating_Change_1M` is today's rating minus the rating of
the same quantity 21 sessions earlier.

**Timing score** (0-100), component weights declared, not fitted:

| Component | Weight | Definition |
|---|---|---|
| Stage | 40% | Stage 2 = 100, S2 Candidate = 70, Stage 1 = 40, Stage 3 = 20, Stage 4 = 0 |
| RS rating | 20% | 1-99 as above |
| RS trend | 20% | percentile of `RS_Rating_Change_1M` |
| Extension | 20% | 100 up to 25% above MA150, linear to 0 at 75% above; 50 below MA150 (already priced by stage) |

Undefined stage (fewer than 221 sessions) → no timing score → blended at a
neutral 50, the factor blocks' own rule for absent evidence.

**Action score.** `(1 − w) · Research_Score + w · Timing_Score`.

### Calibration, done before this document and without looking at returns

The stage and RS definitions were fitted to one third-party stage screener's
labels for the 2026-09-18 cross-section (Stage 2 / S2 Candidate / 3 / 4 exports,
1,417 names matched). Only labels were compared -- no forward return was
computed, and 2026-09-18 lies after every window below.

| Check | Result |
|---|---|
| Stage label, exact agreement | 90.8% |
| Days in stage, same label, within 7 days | 60% (Stage 2 alone: 76%) |
| RS rating vs their RS percentile, Spearman | 0.976 |
| RS 1-month change, Spearman | 0.858 |

The component weights and the extension thresholds were **not** calibrated; they
are declared above as priors.

## Pre-declared grid

Baseline is `model_5` -- `Research_Score` alone, which is the production
ranking (`RANK_BY_ELIGIBILITY_CLASS=false`).

| Variant | Timing weight w | Stage 4 demotion |
|---|---|---|
| **T0** baseline = `model_5` | 0 | no |
| T1 `model_5_t1_w10` | 0.10 | no |
| T2 `model_5_t2_w20` | 0.20 | no |
| T3 `model_5_t3_w30` | 0.30 | no |
| T4 `model_5_t4_w40` | 0.40 | no |
| T5 `model_5_t5_stage4_demotion_only` | 0 | **yes** -- every Stage 4 name ranked below every other |

T5 exists to separate a hard "never buy a Stage 4" rule from the continuous
blend, so a T1-T4 result can be attributed.

## Windows

The four windows of P1/P2 and the published 5.1 table: BEAR 2018-11→2020-06,
MAIN 2020-07→2025-01, BS_ERA 2023-07→2025-01, FORWARD 2025-02→2025-10.
`--with-fundamentals --timing-grid --horizons 1,3,6 --min-history 200`.

Plus **RECENT 2025-11→2026-06** (signals; 3M forward returns reach 2026-09).
No timing variant has ever been scored on it. The `model_5` baseline was run
over it once as part of `p0_backtest_2025-02-01_2026-08-18`, so it is not a clean
holdout. It is reported, and it counts in the decision rule only as a veto
(criterion 5).

**BEAR caveat, declared now.** The archive starts 2018-01-01. A stage needs 221
sessions and the RS rating 253, so for roughly the first two to three rebalances
of BEAR most names have no timing score and blend at neutral 50. On top of P1's
coverage artifact (quality 0.08, growth 0.03), BEAR is indicative only.

None of the four main windows is a holdout.

## Decision rule, fixed in advance

A timing weight is promoted **only if all of these hold**:

1. Beats T0 on net CAGR versus the equal-weight eligible universe (top 20) in
   **at least 3 of the 4** main windows.
2. Does not degrade FORWARD by more than 2 points versus T0.
3. Does not degrade BEAR maximum drawdown by more than 3 points.
4. **Ordered response.** Across T1→T4 the net CAGR advantage is monotone or
   single-peaked, and the chosen weight's neighbours on the grid are not below
   T0 in a majority of windows. An isolated winner is noise.
5. Not worse than T0 on net CAGR by more than 2 points in RECENT.
6. 3-month rank IC not lower than T0's in at least 2 of the 3 informative
   windows (MAIN, BS_ERA, FORWARD). P2 showed that CAGR rising while rank IC
   falls is the signature of a lucky top-20 rather than a better ordering.

If several weights pass, the **smallest** passing weight is chosen: the least
departure from the validated ranking that captures the effect.

T5 is judged separately against the same criteria 1-3, 5 and 6.

**Mixed result ⇒ the rank does not change.** The stage, RS and entry-state
columns ship regardless as display-only evidence, since they are a labelling
decision the project owner has already made; `Action_Rank` ships only with a
passing weight.

**Even on a clean pass**, promotion is: record here → ship with the weight behind
a `TIMING_WEIGHT` config knob → publish `Action_Rank` beside `Investment_Rank`,
leaving `Investment_Rank` unchanged → let `backtest_history.csv` accumulate live
evidence before any consumer defaults to the new rank.

## Expected effect, declared up front

The timing score overlaps the momentum block, which is already 25% of the
research score; RS rating and momentum percentile will correlate strongly. The
new information is the stage and extension components (60% of the timing score
between them). The expected effect on the top 20 is therefore moderate: T1/T2
should move a handful of names, T4 many. Turnover will rise, because stage
changes faster than 6-12 month momentum, and net CAGR carries that cost.

Directional prior: small positive in MAIN and BS_ERA, where trends persisted;
uncertain in FORWARD, where `momentum_only` was the worst block (−21.31); T5
positive in BEAR if anywhere. Confidence that any T1-T4 clears the full bar:
**~30%**. T5: **~35%**.

## What this cannot establish

* A top-20-always backtest cannot measure abstention -- holding cash when
  nothing is in Stage 2. That is a real use of stage analysis and it is
  invisible here.
* The calibration is one day of one vendor's labels. Agreement says our stage
  resembles theirs, not that either predicts returns.
* The archive has no sector map, so ranking is market-wide, not sector-neutral,
  in every variant including the baseline (as in P0-P2).
* The timing weight is fitted to everything visible, exactly as the 5.1 block
  weights were before they lost FORWARD by 8.1 points.

---

# Result, recorded 2026-09-19

Run: `tools.run_p0_backtest --with-fundamentals --timing-grid --horizons 1,3,6
--min-history 200`, five windows, results in
`reports_advanced/backtest/p3_{bear,main,bs_era,forward,recent}.json`.

## Verdict: NOT PROMOTED. Every variant fails, and the response is ordered the wrong way.

## Net CAGR minus the equal-weight eligible universe (top 20)

| Strategy | BEAR | MAIN | BS_ERA | FORWARD | RECENT |
|---|---|---|---|---|---|
| T0 `model_5` (production ranking) | +22.11 | +25.29 | +27.46 | −6.12 | +9.64 |
| T1 w = 0.10 | +22.79 | +22.43 | +24.18 | −10.56 | +8.73 |
| T2 w = 0.20 | +19.49 | +14.46 | +20.45 | −11.33 | +3.91 |
| T3 w = 0.30 | +18.62 | +12.48 | +16.90 | −11.01 | +5.27 |
| T4 w = 0.40 | +15.84 | +8.48 | +11.59 | −7.88 | +3.01 |
| T5 Stage 4 demotion only | +21.69 | +25.15 | +27.46 | −7.20 | +7.48 |

Advantage over T0, in points:

| | BEAR | MAIN | BS_ERA | FORWARD | RECENT |
|---|---|---|---|---|---|
| T1 | +0.68 | −2.86 | −3.28 | −4.44 | −0.92 |
| T2 | −2.62 | −10.83 | −7.02 | −5.21 | −5.74 |
| T3 | −3.49 | −12.81 | −10.56 | −4.88 | −4.38 |
| T4 | −6.27 | −16.81 | −15.87 | −1.76 | −6.63 |
| T5 | −0.42 | −0.15 | 0.00 | −1.07 | −2.16 |

## Risk, ranking quality and turnover

| Max drawdown % | BEAR | MAIN | BS_ERA | FORWARD | RECENT |
|---|---|---|---|---|---|
| T0 | −17.53 | −15.61 | −13.32 | −8.07 | −17.85 |
| T1 | −16.54 | −15.95 | −10.96 | −6.96 | −18.47 |
| T3 | −13.31 | −16.53 | −13.01 | −8.31 | −18.94 |
| T5 | −17.60 | −15.61 | −13.32 | −8.11 | −18.92 |

| Rank IC 3M | BEAR | MAIN | BS_ERA | FORWARD | RECENT |
|---|---|---|---|---|---|
| T0 | 0.1468 | 0.0780 | 0.1008 | 0.0696 | −0.0856 |
| T1 | 0.1461 | 0.0788 | 0.1007 | 0.0675 | −0.0803 |
| T2 | 0.1444 | 0.0791 | 0.1000 | 0.0645 | −0.0766 |
| T4 | 0.1394 | 0.0780 | 0.0950 | 0.0552 | −0.0926 |
| T5 | 0.1426 | 0.0772 | 0.1023 | 0.0594 | −0.0683 |

| Mean monthly turnover | BEAR | MAIN | BS_ERA | FORWARD |
|---|---|---|---|---|
| T0 | 0.371 | 0.335 | 0.314 | 0.369 |
| T1 | 0.405 | 0.420 | 0.428 | 0.444 |
| T4 | 0.545 | 0.668 | 0.694 | 0.613 |

## Against the pre-registered rule

| Criterion | T1 | T2 | T3 | T4 | T5 |
|---|---|---|---|---|---|
| 1. beats T0 in ≥3 of 4 | 1/4 FAIL | 0/4 FAIL | 0/4 FAIL | 0/4 FAIL | 0/4 FAIL |
| 2. FORWARD not worse by >2pp | −4.44 FAIL | −5.21 FAIL | −4.88 FAIL | −1.76 pass | −1.07 pass |
| 3. BEAR drawdown not worse by >3pp | pass | pass | pass | pass | pass |
| 4. ordered response | ordered, **downward**: more weight, less return | | | | |
| 5. RECENT not worse by >2pp | pass | FAIL | FAIL | FAIL | FAIL |
| 6. IC 3M ≥ T0 in ≥2 of 3 | 1/3 FAIL | 1/3 FAIL | 1/3 FAIL | 1/3 FAIL | 1/3 FAIL |

## Reading

The prior of ~30% was too generous. This is not a mixed result: net CAGR falls
monotonically with the weight in MAIN and BS_ERA, the two long windows, and
turnover roughly doubles at w = 0.40, so part of the cost is trading and part
is selection. Rank IC barely moves at small weights (T1-T2 are within 0.001 of
T0 in MAIN and BS_ERA), which says the blend reshuffles the *top* of the list
rather than improving or damaging the ordering as a whole -- and at the top,
where the research scores are packed between 97 and 100, the timing score
decides almost everything, which is the mechanism behind the losses.

The one improvement is BEAR drawdown (−17.53 to −13.31 at T3), the only place a
stage filter did what stage analysis promises. It did not buy back the return.

T5 isolates "never rank a Stage 4 above anything else": close to neutral in the
long windows and negative in FORWARD and RECENT. Stage 4 names at the top of the
research ranking were not systematically the losers the rule assumes.

This repeats the repo's standing finding -- p0 eligibility-first ranking, P2
momentum floors -- that trend conditions used as selection inputs cost this
model return.

## What ships

Per the decision rule: `TIMING_WEIGHT` stays 0, and at 0 `Action_Rank` and
`Action_Score` are not published (they would duplicate `Investment_Rank`). The
stage, RS rating, advance age and entry-state columns ship as display-only
evidence, as agreed before the run. The knob and the T1-T5 grid stay so the
result can be re-tested on later data, not tuned.

## What this does not refute

A top-20 monthly rotation measures stage as a *ranking* input. It does not test
stage as an entry-timing rule for one name the reader has already chosen -- buy
on a Stage 2 entry, wait through a pullback -- nor abstention: holding cash when
nothing is in Stage 2. Those need a different experiment and remain open.

Also noted, outside this experiment: the production ranking itself had negative
3-month rank IC in RECENT (−0.086), while still beating the equal-weight
universe by 9.6 points on CAGR.
