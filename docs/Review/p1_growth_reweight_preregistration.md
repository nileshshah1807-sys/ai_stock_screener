# P1 pre-registration: does weighting deceleration harder help?

Written **before** the grid was run. Committed first so the decision rule cannot
be adjusted after seeing which variant won. This is condition 8 of the
validation protocol in `docs/model_methodology.md` ("Test the grid, not the
winner") applied to a within-block weight change.

Author: research session, 2026-08-25.
Baseline commit: `a0f53c7`.

## The question

The Model 5.1 growth block weights *trailing level* (how fast has it grown)
more heavily than *turning* (is that growth speeding up or slowing down):

| Input | Weight | Kind |
|---|---|---|
| `Revenue_CAGR_3Y` | 0.25 | trailing level |
| `EPS_CAGR_3Y` | 0.20 | trailing level |
| `Revenue_Acceleration` | 0.15 | turning |
| `EPS_Acceleration` | 0.15 | turning |
| `Margin_Direction` | 0.15 | turning |
| `Cash_Conversion` | 0.10 | cash confirmation |

Trailing level carries **0.45**, turning carries **0.45**, confirmation 0.10.

The motivating observation is a single name. On 2026-08-24 LUPIN ranked 14 of
2,383 with `Research_Score` 99.45, while `EPS_Acceleration` sat at the **9th
percentile** of the universe and the market was pricing a 15.3% earnings
decline (trailing PE 18.13 against forward PE 21.40). The trailing input
(`EPS_CAGR_3Y` = 1.31) outvoted the turning input at a 0.20/0.15 ratio.

**One name is an anecdote, not evidence.** The question this grid asks is
whether tilting the block toward turning signals helps *on average, across the
whole archive* — which is the only form of the question the data can answer.

## Pre-declared grid

A monotonic ladder from trailing-heavy to turning-heavy. A ladder is declared
rather than a single alternative so the result shows a *direction* — if the
effect is real, the response should be ordered, not a single lucky point.

| Variant | Rev CAGR | EPS CAGR | Rev Accel | EPS Accel | Margin Dir | Cash Conv | Level/Turning |
|---|---|---|---|---|---|---|---|
| **G0** baseline (5.1 production) | 0.25 | 0.20 | 0.15 | 0.15 | 0.15 | 0.10 | 45 / 45 |
| **G1** minimal swap | 0.25 | 0.15 | 0.15 | 0.20 | 0.15 | 0.10 | 40 / 50 |
| **G2** deceleration-tilted | 0.20 | 0.15 | 0.20 | 0.20 | 0.15 | 0.10 | 35 / 55 |
| **G3** turning-dominant | 0.15 | 0.10 | 0.25 | 0.25 | 0.15 | 0.10 | 25 / 65 |

`Cash_Conversion` is held at 0.10 throughout so the ladder varies one thing.

Controls carried in the same run, unchanged: `model_5` (= G0), `model_5_gated`,
`value_only`, `growth_only`, `quality_only`, `momentum_only`,
`simple_quality_momentum`, `equal_weight_universe`, `random_ranking`.

## Expected effect size, declared up front

The growth block is **20%** of `Research_Score`. The largest weight shift in the
ladder (G3) moves 20 percentage points *within* that block, so the maximum
possible change to any security's blended input is ~4% of one block, or **~0.8%
of the raw score** before the percentile re-rank.

**A large swing in net CAGR from this change would be evidence of noise, not
signal.** Realistic expectation: differences in the low single digits of net
CAGR, well inside the run-to-run variation of a 20-name portfolio. This is
written down now so a +15 point result is read with suspicion rather than
celebration.

## Windows

The same four as the 5.1 exercise, so results are comparable to the published
table:

| Window | Dates | Rebalances |
|---|---|---|
| BEAR | 2018-11-01 → 2020-06-30 | 19 |
| MAIN | 2020-07-01 → 2025-01-31 | 54 |
| BS_ERA | 2023-07-01 → 2025-01-31 | 18 |
| FORWARD | 2025-02-01 → 2025-10-31 | 8 |

Run parameters match the published run: `--with-fundamentals`,
`--horizons 1,3,6`, `--min-history 200`.

Every one of these windows has already been examined during the 5.0 → 5.1
weight change. **None of them is a holdout.** They can show whether the reweight
is *consistent*; they cannot show that it is *predictive*. That distinction is
the reason for the decision rule below.

## Decision rule, fixed in advance

A variant is promoted to production **only if all four hold**:

1. It beats G0 on net CAGR versus the equal-weight eligible universe in **at
   least 3 of the 4 windows**.
2. It does **not** degrade FORWARD, the least-fitted window, by more than 2
   points versus G0.
3. Rank IC at the 3-month horizon is **greater than or equal to** G0's in at
   least 3 of the 4 windows.
4. The response across the ladder is **ordered** (G1 ≤ G2 ≤ G3 or
   G1 ≥ G2 ≥ G3 in direction of effect). A win by G2 alone, with G1 and G3
   both losing, is a single lucky point and is treated as noise.

**If the result is mixed, nothing changes.** Model 5.1 ships as it is and the
finding is recorded as "no measured improvement". A null result is a valid and
publishable outcome of this exercise, and is the outcome the base rate favours.

**Even if all four criteria hold**, the promotion path is not an immediate
weight change in production. It is:

1. Record the result here.
2. Ship the change **behind `FACTOR_GROWTH_FEATURE_WEIGHTS`**, defaulted to G0,
   so production behaviour is unchanged on merge.
3. Wait for genuine out-of-sample evidence from `backtest_history.csv`, which
   has been accumulating on every scheduled run since 5.1 went live and is the
   only untouched data this project owns.
4. Flip the default only when that live evidence agrees.

The 5.0 → 5.1 change is the cautionary precedent: it won BEAR, MAIN and BS_ERA
and then lost FORWARD by 8.1 points, the freshest window. Weights fitted on
everything visible are not validated by everything visible.

## What this cannot establish

* Not point-in-time free of the fitting that produced 5.1 — the archive has been
  fully examined.
* The DCF block stays disabled (no capex in the results XBRL), so the value
  block runs on four inputs here and five in production.
* Ranking is market-wide, not sector-neutral; no survivorship-free
  point-in-time sector map exists.
* Balance-sheet inputs are absent before FY2023, so quality-block coverage is
  thinner in BEAR and MAIN than in production.
* A 20-name top-N backtest cannot measure the gates' abstention value.

---

# Result, recorded 2026-08-25

Run: `tools.run_p0_backtest --with-fundamentals --growth-reweight-grid`, four
windows, `--horizons 1,3,6 --min-history 200`, results in
`reports_advanced/backtest/p1_{bear,main,bs_era,forward}.json`.

## Verdict: NULL. No production change.

## Net CAGR minus the equal-weight eligible universe

| Strategy | BEAR | MAIN | BS_ERA | FORWARD |
|---|---|---|---|---|
| model_5 (G0, production) | +23.86 | +23.87 | +25.25 | −7.02 |
| G1 minimal swap | +23.86 | +26.34 | +28.15 | −6.95 |
| G2 deceleration-tilted | +22.11 | +22.37 | +25.41 | −2.44 |
| G3 turning-dominant | +23.86 | +23.37 | +17.87 | −3.92 |

Controls, unchanged from the 5.1 exercise and reported in full:

| Strategy | BEAR | MAIN | BS_ERA | FORWARD |
|---|---|---|---|---|
| value_only | +29.26 | +45.32 | +32.59 | +23.80 |
| growth_only | −7.12 | +6.36 | +19.31 | +24.40 |
| momentum_only | +14.59 | +2.15 | +25.33 | −21.31 |
| quality_only | −2.90 | −8.41 | −2.19 | −14.87 |
| model_5_gated | +23.86 | +22.05 | +17.98 | −10.09 |
| random_ranking | −14.94 | −24.81 | −30.16 | −27.42 |

## Mean rank IC, 3-month horizon

| | BEAR | MAIN | BS_ERA | FORWARD |
|---|---|---|---|---|
| G0 | +0.15 | +0.08 | +0.10 | +0.07 |
| G1 | +0.15 | +0.08 | +0.10 | +0.07 |
| G2 | +0.15 | +0.08 | +0.10 | +0.07 |
| G3 | +0.15 | +0.08 | +0.10 | +0.07 |

**Identical to two decimals in every window.** The direct measure of ranking
quality did not move. Whatever the CAGR column is showing, it is not a better
ranking.

## Against the decision rule

| Criterion | G1 | G2 | G3 |
|---|---|---|---|
| 1. beats G0 in ≥3 of 4 windows | 3/4 PASS | 2/4 FAIL | 1/4 FAIL |
| 2. FORWARD not worse by >2pp | PASS (+0.08) | PASS (+4.58) | PASS (+3.10) |
| 3. rank IC ≥ G0 in ≥3 windows | 3/4 PASS | 3/4 PASS | 3/4 PASS |
| 4. ordered response across ladder | **FAIL** | **FAIL** | **FAIL** |

Criterion 4 fails for the ladder as a whole, and it is the criterion that
exists to catch exactly this. The per-window orderings disagree completely:

* MAIN: G1 > G0 > G3 > G2
* BS_ERA: G1 > G2 > G0 > G3
* FORWARD: G2 > G3 > G1 > G0
* BEAR: G0 = G1 = G3 > G2

The best variant in one window is near-worst in another. Turning the dial
further does not reliably help or reliably hurt, which is the signature of
noise rather than a real effect. Promotion requires all four criteria; nothing
is promoted.

## Why G1's apparent 3/4 win is not a win

G1 is barely a different model:

| Variant vs G0 | rank corr | top-20 shared | mean score move |
|---|---|---|---|
| G1 | 0.9972 | **19/20** | 1.28 |
| G2 | 0.9904 | 17/20 | 2.76 |
| G3 | 0.9602 | 13/20 | 5.56 |

(2024-06-28 cross-section, 2,129 securities; 2025-06-30 is identical to three
decimals.)

G1 changes **one name in the top 20**. Its +2.47 (MAIN) and +2.90 (BS_ERA)
"improvement" is one substituted stock's return in a 20-name portfolio. And the
variant that genuinely changes the ranking, G3, is the one that does worst
(+17.87 against G0's +25.25 in BS_ERA) — the opposite of the hypothesis.

This is the outcome the pre-declared effect-size note anticipated: the growth
block is 20% of the score, the largest shift moves a raw score by under 1%, so
CAGR swings of several points are portfolio-composition luck.

## What this establishes

**The LUPIN failure mode is not reachable by reweighting inside the growth
block.** `EPS_Acceleration` is already in the block and already point-in-time;
weighting it up to a third of the block does not change what the model ranks
highly. A model that distinguishes "great past, deteriorating present" needs an
input it does not currently carry, not a redistribution of the ones it has.

## Defect found during the run: the archive cannot test this in BEAR

The XBRL panel spans FY2017–FY2024, and NSE's filings feed begins 2018-02-14.
FY2017 carries only 549 securities against ~1,950 for FY2024. Consequently, at
a bear-window date:

| As of | ≥2 yrs (EPS YoY) | ≥3 yrs (`EPS_Acceleration`) | ≥4 yrs (`EPS_CAGR_3Y`) |
|---|---|---|---|
| 2019-06 (BEAR) | 70.1% | 23.0% | **0.0%** |
| 2021-06 (early MAIN) | 92.0% | 82.0% | 58.1% |
| 2024-06 (BS_ERA) | 92.4% | 85.9% | 77.1% |
| 2025-06 (FORWARD) | 92.1% | 85.6% | 76.9% |

Measured block coverage and dispersion on the same code:

| As of | Quality cov | Growth cov | Quality std | Growth std |
|---|---|---|---|---|
| 2019-06 | 0.08 | 0.03 | 2.23 | 1.98 |
| 2020-03 | 0.09 | 0.04 | 2.44 | 2.19 |
| 2021-06 | 0.19 | 0.48 | 4.23 | 10.88 |
| 2024-06 | 0.66 | 0.69 | 11.34 | 11.47 |

A fully covered block has std ~14–23. At std ≈ 2 a block is pinned at 50 for
the whole cross-section and ranks nothing.

**In the bear window, quality (25%) and growth (20%) — 45% of Model 5.1's
weight — were inert.** What ranked stocks there was value, momentum and risk.

This is a limitation of the validation archive, not of production: the live
2026-08-24 run reports `Quality_Coverage` and `Growth_Coverage` of 1.00,
because Yahoo's annual statements reach back far enough.

It bears on one claim in `p0_implementation_plan.md` §8.2 — that the bear
window's −16.04% drawdown against the universe's −43.18% is "the argument
against concentrating further into value." The drawdown protection is real, but
it came from a three-block model. The bear window cannot argue for keeping the
two blocks that were switched off in it.

The §8.2 reasoning for the *quality weight cut* is unaffected: it rests
explicitly on BS_ERA and FORWARD, where quality coverage is 0.66 and its
inputs are real.

The floor is structural. NSE's filings feed does not reach earlier, so no
backfill fixes the bear window.
