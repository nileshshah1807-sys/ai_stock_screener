# P8 pre-registration: the trailing stop, judged on live rankings only

Written on 2026-09-27, **before** any of the data that will judge it exists.
Same reason as P1-P7; this is the only clean test left for a portfolio rule,
because every past period has now been looked at (P7 spent the held-out year).

## Why this rule

Across 3,552 rolling windows from 2019 to 2026 (the rolling-window section
of `returns_filter_study_2026-09-27.pdf`), the 20% trailing stop was the only
drawdown rule that helped with any consistency. On the unfiltered Top 20,
rebalanced monthly and held as bought, it made the worst fall shallower in 81%
of one-year windows and every three-year window -- by a median 2.1 points, and
5.2 in falling markets -- for about 2.8 points a year of return. It was chosen
*after* seeing those runs, so none of them can confirm it.

## What is compared

Both buy the unfiltered ranking's Top 20 from **published** rankings (never
backtest ones), rebalance monthly, hold kept stocks as bought, 100% invested,
0.3% cost per side -- the Returns engine (`dashboard/lib/returns.mjs`) as of
this commit.

* **Base** - as above.
* **Stop** - the same, plus: a holding that closes 20% below its highest close
  since purchase is sold at its next close; the money waits in cash for the
  next monthly rebalance, which refills by the normal rules.

## Period

First purchase: the session after the first published NSE ranking on or after
**28 Sep 2026**. Checked at 6 months (end of March 2027) for information only;
**decided at 12 months** (the last session of September 2027).

## Decision rule (fixed now)

At 12 months, adopt the stop only if **both**:

1. the stop's worst fall is at least **2 points shallower** than the base's, and
2. its return is no more than **5 points** below the base's.

If the base's own worst fall over the year is shallower than **-10%**, the year
had no real fall to test against: the decision is deferred and re-checked every
6 months under the same two conditions, until either condition 1 can be judged
or the owner stops the test.

Nothing about the rule, its 20%, the basket or the dates changes while the test
runs. The 6-month check is reported, not acted on.

## How to run the check

```bash
cd dashboard && set -a && . ../.env && set +a
node scripts/research/data.mjs holdout      # refreshes published rankings and prices
node scripts/research/p8-forward.mjs
```

## Result

_Not before 31 Mar 2027 (6-month look) and 30 Sep 2027 (decision)._
