# P7 pre-registration: portfolio rules to cap the drawdown

Written **after** the design-period runs below and **before** any rule was run on
the held-out year, for the same reason as P1-P6. This study changes how the
Returns basket is run; it changes no score, rating or rank.

Author: research session, 2026-09-27. Branch `research/p7-drawdown` follows
`main` at `1b83e87`.

## Why

The filter study of 2026-09-27 (324 Returns-engine runs, NSE backtest,
31 Dec 2018 - 30 Sep 2025) found that no rating or stage filter lowered the
drawdown, and that the basket's three worst falls were the market's
(2020, 2022, Jan-Mar 2025), 1.1-2.2x deeper. The owner's goal: **keep the
worst fall inside about -20%, then maximise return.**

## Periods

* **Design:** first purchase 31 Dec 2018 to 30 Sep 2025. Everything below.
* **Holdout:** rankings from 1 Oct 2025 to the latest run. Looked at **once**,
  for the chosen rule and its base only, after this file is committed.

## Bases

Both buy the unfiltered ranking's top 20, 0.3% cost per side.

* **A** - rebalanced weekly, every holding reset to equal weight.
* **B** - rebalanced monthly, kept holdings held as bought.

## Rules (numbers fixed in advance, not tuned)

Checked once per calendar week, on that week's first ranking; trades at the
next session's close.

* **R1 Market switch.** `classify_regime` (screener/benchmark.py: 200-session
  average, its 20-session slope, 2% band) on the Nifty 500. RISK_OFF: sell
  everything, hold cash. Buy back at the first weekly check that is not
  RISK_OFF, from that week's ranking.
* **R2 Small-cap switch.** The same rule on `universe_index`, the equal-weight
  index of every ranked stock (starts 2018-11-06, so it can first act in
  about Sep 2019).
* **R3 Trailing stop.** A holding that closes 20% below its highest close since
  purchase is sold at its next close; the money waits in cash for the next
  rebalance, which refills by the normal rules (the stock may be bought back
  if it still ranks).

Every subset of R1-R3 was run on both bases (16 runs), at the owner's request.

## Design results

Nifty 500 over the same window: 14.4% a year, worst fall -38.3%.

| Base | Rules | CAGR | Worst fall | CAGR / fall | Sharpe | Weeks in cash | Stops |
|---|---|---|---|---|---|---|---|
| A | none | 50.8% | -48.0% | 1.06 | 1.93 | 0% | 0 |
| A | R1 | 37.3% | -35.6% | 1.05 | 1.64 | 10% | 0 |
| A | R2 | 43.5% | -30.1% | 1.44 | 1.88 | 11% | 0 |
| A | R3 | 49.5% | -41.9% | 1.18 | 1.96 | 0% | 259 |
| A | R1 + R2 | 37.3% | -30.7% | 1.21 | 1.68 | 15% | 0 |
| A | R1 + R3 | 37.0% | -29.9% | 1.24 | 1.67 | 10% | 220 |
| A | R2 + R3 **(chosen)** | 42.5% | -26.5% | 1.60 | 1.89 | 11% | 220 |
| A | R1 + R2 + R3 | 36.1% | -27.8% | 1.30 | 1.67 | 15% | 207 |
| B | none | 50.1% | -41.5% | 1.21 | 1.89 | 0% | 0 |
| B | R1 | 33.7% | -30.4% | 1.11 | 1.51 | 10% | 0 |
| B | R2 | 41.7% | -29.1% | 1.43 | 1.81 | 11% | 0 |
| B | R3 | 49.9% | -27.6% | 1.81 | 2.13 | 0% | 266 |
| B | R1 + R2 | 34.1% | -30.4% | 1.12 | 1.57 | 15% | 0 |
| B | R1 + R3 | 33.9% | -29.0% | 1.17 | 1.65 | 10% | 233 |
| B | R2 + R3 | 40.3% | -27.6% | 1.46 | 1.91 | 11% | 235 |
| B | R1 + R2 + R3 | 33.0% | -29.0% | 1.14 | 1.65 | 15% | 221 |

## Choice

Rule, fixed before the runs: highest CAGR among runs with a worst fall inside
-20%; if none, the shallowest worst fall among runs that beat the Nifty 500.

No run stays inside -20%. The shallowest worst fall that beats the index is
**A + R2 + R3: 42.5% a year, worst fall -26.5%** (A alone: 50.8%, -48.0%).

Recorded concerns, before the holdout:

1. Its gain is concentrated in one event. It cut the 2020 crash from -48.0%
   to -26.5% but barely moved the Jan-Mar 2025 fall (-27.0% to -26.2%) or
   2022 (-24.0% to -23.6%); a two-month fall is faster than a 200-session
   switch. In 2025 to September it did worse than A (-19% vs -13%).
2. B + R3 is close (49.9%, -27.6%) at almost no cost in return, and is the
   best CAGR / fall of all 16. It is **not** the pre-registered choice and is
   not tested on the holdout; noting it here is the only use made of it.

## Holdout test

Run once: A + R2 + R3 and A alone, first purchase after the first ranking on
or after 1 Oct 2025, to the latest run.

Adopt A + R2 + R3 only if, on the holdout,

* its worst fall is at least a third smaller than A's (|fall| <= 2/3 of A's), **and**
* its total return is at least the Nifty 500's over the same dates.

Otherwise it is not adopted, and the holdout is spent.

## Holdout result

_To be filled in after the single run._
