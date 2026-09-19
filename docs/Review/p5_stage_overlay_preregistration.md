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
