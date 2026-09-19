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
