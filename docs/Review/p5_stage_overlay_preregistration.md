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

**Correction before this was read.** The first run had a window-boundary bug: a
window's final holding period ran to the end of the archive instead of to the
next rebalance, so DISCOVERY silently held its December 2022 portfolio through
2023-2026. A year-by-year check exposed it (DISCOVERY showed 2023-2026 returns).
`simulate` now takes the schedule's next rebalance as `closing`. CONFIRM ended
at the end of the data and was unaffected; its numbers are identical in both
runs. The first run's verdict (X34 failing on DISCOVERY return) came from the
bug and is withdrawn; the tables below are the corrected run.

## Verdict: X34 (sell on a break into Stage 3 or 4) PASSES, on both schedules.

X4 (Stage 4 only) and every breadth cash switch fail.

## Monthly rebalance

| | DISCOVERY CAGR | Sharpe | Max DD | CONFIRM CAGR | Sharpe | Max DD | exits |
|---|---|---|---|---|---|---|---|
| **B0** baseline | 40.96 | 1.323 | −42.99 | 39.08 | 1.376 | −26.94 | 0 |
| X4 Stage 4 exit | 40.37 | 1.320 | −42.36 | 38.27 | 1.352 | −26.94 | 17 / 14 |
| **X34 Stage 3/4 exit** | **43.23** | **1.577** | **−29.63** | **39.35** | **1.469** | **−21.87** | 144 / 124 |
| C10-50 | 38.94 | 1.291 | −42.99 | 35.02 | 1.286 | −26.94 | |
| C10-100 | 36.61 | 1.226 | −42.99 | 30.87 | 1.148 | −31.41 | |
| C20-50 | 34.34 | 1.163 | −42.99 | 36.69 | 1.379 | −21.92 | |
| C20-100 | 27.47 | 0.942 | −42.99 | 33.92 | 1.305 | −25.49 | |

## Quarterly rebalance (3-month hold)

| | DISCOVERY CAGR | Sharpe | Max DD | CONFIRM CAGR | Sharpe | Max DD |
|---|---|---|---|---|---|---|
| **B0** | 40.04 | 1.302 | −40.34 | 39.39 | 1.380 | −28.84 |
| X4 | 38.52 | 1.274 | −40.11 | 37.68 | 1.336 | −29.17 |
| **X34** | 38.60 | **1.545** | **−23.52** | 39.49 | **1.609** | **−20.15** |

## Against the rule

| | Sharpe +0.05, both | Drawdown not worse by >2, both | CAGR not lower by >2, both | Result |
|---|---|---|---|---|
| X4 monthly | FAIL (−0.003, −0.024) | pass | pass | not promoted |
| X4 quarterly | FAIL | pass | pass | not promoted |
| **X34 monthly** | pass (+0.254, +0.093) | pass (13.4 and 5.1 shallower) | pass (+2.27, +0.27) | **PASS** |
| **X34 quarterly** | pass (+0.243, +0.229) | pass (16.8 and 8.7 shallower) | pass (−1.44, +0.10) | **PASS** |
| C10/C20 (all four) | FAIL (lower Sharpe in DISCOVERY) | unchanged or worse | FAIL for three | not promoted |

## Where X34's edge comes from (monthly, one continuous run)

| year | B0 | X34 | difference | B0 worst DD | X34 worst DD |
|---|---|---|---|---|---|
| 2019 | −3.1 | −0.5 | +2.6 | −17.9 | −14.5 |
| **2020** | 66.4 | 87.2 | **+20.8** | **−43.0** | **−29.6** |
| 2021 | 136.1 | 134.4 | −1.7 | −15.0 | −14.8 |
| 2022 | 7.5 | 0.6 | −6.9 | −22.3 | −21.6 |
| 2023 | 80.5 | 79.7 | −0.8 | −17.1 | −17.0 |
| 2024 | 68.3 | 63.1 | −5.2 | −12.2 | −12.1 |
| 2025 | −8.3 | −4.7 | +3.6 | −26.9 | −21.9 |
| 2026 (to Sep) | 10.4 | 12.5 | +2.1 | −20.0 | −15.2 |

February-April 2020: B0 −19.0%, X34 −7.3%.

It is insurance, and it behaves like insurance: it pays in the declines (2020,
2025, 2026), costs a few points in steady advances (2022, 2024), and roughly
breaks even in between. **Much of the DISCOVERY return edge is one episode --
the 2020 crash.** The drawdown and Sharpe improvement is broader: the worst
drawdown is shallower or equal in every year.

## Cost sensitivity (not part of the rule; recorded as a robustness check)

X34 trades about 3 exits a month out of 20 holdings.

| cost per side | DISCOVERY CAGR / Sharpe / MaxDD vs B0 | CONFIRM CAGR / Sharpe / MaxDD vs B0 |
|---|---|---|
| 0.30% (declared) | +2.27 / +0.254 / +13.4 | +0.27 / +0.093 / +5.1 |
| 0.60% | +1.62 / +0.215 / +13.1 | −0.35 / +0.061 / +4.8 |

It still passes the rule at double the declared cost.

## Why X4 fails and X34 does not

By the time a top-20 holding reaches Stage 4 -- below a falling 200-day average
-- most of the fall has happened; selling there locks it in. Stage 3 fires
earlier: the close breaks the 150-day average while the long averages still
rise. That is the point at which an exit still saves something.

## The breadth cash switch does not work

It missed the 2020 crash: breadth was 17.9% at end-February 2020, above the
DISCOVERY median of 16.7%, and fell to 2.2% only after the crash, by end-March.
It then held cash into the recovery. Every variant lowered Sharpe in DISCOVERY.

## What this means in practice

The model -- ranking and published ratings -- does not change: this is a rule
about **holdings between rebalances**, and the screener does not know what the
reader holds. It belongs where holdings live: a watchlist alert when a held name
breaks into Stage 3 or 4 (the P5 rule would sell it at the next close), and
optionally a line in the daily email for the current top 20.

Caveats as declared: delisted names are carried at their last price, costs are
a flat rate, the CONFIRM window overlaps data seen in P4, and the DISCOVERY
return edge rests heavily on 2020. This is evidence for the rule, not proof;
the live runs from 2026-09 are its first unseen data.
