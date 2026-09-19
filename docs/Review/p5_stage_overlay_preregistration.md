# P5 pre-registration: stage as an exit rule and as a cash switch

Written **before** any variant's returns were computed. Follows
`p3_stage_timing_preregistration.md` (stage as a ranking input: refuted) and
`p4_stage_diagnostics.md` (why, and what stage still predicts).

Author: research session, 2026-09-19. Branch `feat/stage-exit-breadth-study`
from `main` at `0ac21ec`.

## Why these two

P3 and P4 tested stage as a *selection* input and found nothing. Two uses remain
that a top-20-always ranking backtest cannot see:

1. **Exit.** Universe-wide, Stage 4 beat the market in 15% of months and lost
   4.8 points over six months (P4 §1). A holding that *breaks into* Stage 4
   after purchase may be worth selling before the next rebalance.
2. **Abstention.** When few stocks are in Stage 2, the market is broadly in
   decline; holding cash then may cut drawdowns.

## Set-up, fixed now

* **Selection:** the research top 20 by `Research_Score` from point-in-time
  Model 5 cross-sections (`tools/build_research_panel.py`), the production
  ranking. Every variant holds exactly these names at each rebalance.
* **Simulation:** daily, adjusted closes from the NSE archive, equal weight at
  entry, buy and hold to the next rebalance. Entry at the close of the session
  after the signal date. Suspended or delisted names are carried at their last
  price (the runner's haircut policy is not reproduced here).
* **Costs:** 0.30% of traded value on every buy and every sell, including
  exits and moves into or out of cash. **Cash** earns 6% a year.
* **Stages:** `screener.stage.classify_stages`, computed daily.
* **Breadth:** the share of the liquid universe (60-session median turnover of
  ₹20 lakh or more) classified Stage 2, measured on the signal date.
* **Schedules:** monthly rebalance. Exit variants also run on a quarterly
  schedule (3-month hold, averaged over the three phase offsets), because an
  exit rule has more to do in a longer hold.

## Variants

| Variant | Rule |
|---|---|
| **B0** | baseline: hold the research top 20 |
| **X4** | sell a holding the session after it **breaks into Stage 4**; hold cash until the next rebalance. A name already in Stage 4 at purchase is not sold for it -- the rule is about deterioration, not about the buy decision |
| **X34** | as X4, but on a break into Stage 3 **or** 4 |
| **C10-50** | 50% cash for the period when breadth < 7.3% (the DISCOVERY 10th percentile) |
| **C10-100** | 100% cash when breadth < 7.3% |
| **C20-50** | 50% cash when breadth < 9.1% (DISCOVERY 20th percentile) |
| **C20-100** | 100% cash when breadth < 9.1% |

The breadth thresholds were set from the distribution of breadth over the
DISCOVERY rebalances (10th and 20th percentiles; median 16.7%) before any
return was computed, and are held fixed for CONFIRM.

## Windows

DISCOVERY 2018-11 to 2022-12, CONFIRM 2023-01 to 2026-08. The P4 universe
diagnostics overlap CONFIRM, so it is not pristine; no variant in this document
has been evaluated on either window before.

## Decision rule, fixed in advance

These are risk rules, so they are judged on risk-adjusted return. A variant is
promoted only if, **in both windows**:

1. Sharpe ratio is at least 0.05 above B0's on the same schedule, and
2. maximum drawdown is not worse than B0's by more than 2 points, and
3. CAGR is not below B0's by more than 2 points.

A variant that passes in one window only is recorded as not promoted. If more
than one passes, the simplest (fewest trades) is preferred.

## What this cannot establish

* The breadth rule fires on few periods by construction (10-20% of DISCOVERY
  rebalances), so a pass rests on a handful of episodes, mostly one or two
  market declines.
* Carrying delisted names at their last price flatters any variant that holds
  them and understates what an exit saves.
* Costs are a flat rate, not the runner's liquidity-scaled impact model.

---

# Result, recorded 2026-09-19

Run: `tools.stage_overlay_study`, report in
`reports_advanced/backtest/p5_overlay.json`. Quarterly figures are the mean of
the three phase offsets.

## Verdict: NOT PROMOTED. No variant clears the rule in both windows.

The Stage 3/4 exit (X34) is a clear **risk** improvement in both windows and a
return cost in DISCOVERY; it fails criterion 3 there and is recorded as a
trade-off, not an improvement.

## Monthly rebalance

| | DISCOVERY CAGR | Sharpe | Max DD | CONFIRM CAGR | Sharpe | Max DD | exits |
|---|---|---|---|---|---|---|---|
| **B0** baseline | 36.42 | 1.171 | −42.99 | 39.08 | 1.376 | −26.94 | 0 |
| X4 Stage 4 exit | 32.68 | 1.213 | −42.36 | 38.27 | 1.352 | −26.94 | 36 / 14 |
| **X34 Stage 3/4 exit** | 32.37 | **1.441** | **−29.63** | 39.35 | **1.469** | **−21.87** | 161 / 124 |
| C10-50 | 35.38 | 1.152 | −42.99 | 35.02 | 1.286 | −26.94 | |
| C10-100 | 34.16 | 1.118 | −42.99 | 30.87 | 1.148 | −31.41 | |
| C20-50 | 32.97 | 1.085 | −42.99 | 36.69 | 1.379 | −21.92 | |
| C20-100 | 29.31 | 0.971 | −42.99 | 33.92 | 1.305 | −25.49 | |

## Quarterly rebalance (3-month hold)

| | DISCOVERY CAGR | Sharpe | Max DD | CONFIRM CAGR | Sharpe | Max DD |
|---|---|---|---|---|---|---|
| **B0** | 38.59 | 1.260 | −41.99 | 39.39 | 1.380 | −28.84 |
| X4 | 33.32 | 1.253 | −40.11 | 37.68 | 1.336 | −29.17 |
| **X34** | 28.29 | **1.383** | **−23.52** | 39.49 | **1.609** | **−20.15** |

## Against the rule

| | Sharpe +0.05, both | Drawdown not worse by >2, both | CAGR not lower by >2, both | Result |
|---|---|---|---|---|
| X4 monthly | FAIL (+0.04, −0.02) | pass | FAIL (−3.7) | not promoted |
| X4 quarterly | FAIL | pass | FAIL (−5.3) | not promoted |
| X34 monthly | pass (+0.27, +0.09) | pass (+13.4, +5.1 better) | **FAIL (−4.1 in DISCOVERY)**; +0.3 in CONFIRM | not promoted |
| X34 quarterly | pass (+0.12, +0.23) | pass (+18.5, +8.7 better) | **FAIL (−10.3 in DISCOVERY)**; +0.1 in CONFIRM | not promoted |
| C10/C20 (all four) | FAIL (lower Sharpe in DISCOVERY) | FAIL or unchanged | FAIL | not promoted |

## Reading

**Selling on a break into Stage 4 alone does nothing useful.** By the time a
holding from the research top 20 reaches Stage 4 most of the damage is done; X4
cut return in both windows without improving Sharpe.

**Selling on a break into Stage 3 or 4 is a real risk control.** Volatility fell
by a quarter to a third, and the worst drawdown by 13-18 points in DISCOVERY and
5-9 in CONFIRM, with Sharpe higher in every window and schedule. It cost return
in DISCOVERY -- 4 points a year monthly, 10 quarterly -- almost all of it in the
2020-21 recovery, when names that broke down in the crash rebounded after being
sold. In CONFIRM it cost nothing. It trades heavily: about 3 exits a month out
of 20 holdings, all charged at 0.30% a side.

**The breadth cash switch does not work.** It missed the 2020 crash entirely --
breadth was normal in February 2020 and the fall came inside one month -- and
it held cash through recoveries. Every variant lowered Sharpe in DISCOVERY.

## What this means in practice

Nothing in the model changes: the ranking and the published ratings stay as
they are. X34 is a legitimate choice for a holder who prefers a shallower
drawdown to the last few points of return in a V-shaped recovery, and it is
made per portfolio, not per model. If it is wanted, the useful product is a
watchlist alert -- "a holding broke into Stage 3 or 4" -- not a rank change.

Caveats as declared: delisted names are carried at their last price, costs are
a flat rate, and the CONFIRM window overlaps data seen in P4.
