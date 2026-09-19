# P4: why the timing blend lost, and whether any stage rule helps the rank

Follows `p3_stage_timing_preregistration.md`, which refuted every timing weight.
This document asks the two questions that result raised -- *what* made returns
worse, and whether a different stage rule (including "bonus points when a stock
enters Stage 2") would do better -- and records the outside research.

Author: research session, 2026-09-19.

## Method, and its honest limits

* **Universe-wide, price only.** The local NSE archive, 2022-01 to 2026-06, 56
  month-ends, ~1,500 liquid names a month (median 60-day turnover ≥ ₹20 lakh).
  Stage from `screener/stage.py` rules; forward returns close to close, excess
  over the equal-weighted universe that month, averaged per monthly cohort.
* **Inside the model's top of list.** Point-in-time Model 5 cross-sections from
  the backtest runner, 2018-11 to 2026-08, 94 rebalances, 113,652 rows, with
  research score, stage inputs and 1/3/6/12-month forward returns.
* **Variant search was split.** Rules were chosen on DISCOVERY (2018-11 to
  2022-12) and only looked at on CONFIRM (2023-01 to 2026-06/03). The universe
  diagnostics above overlap CONFIRM and were seen first, so CONFIRM is not a
  pristine holdout. Returns in the variant tables are gross of costs.

## 1. Stage does carry information -- universe-wide

Forward excess return vs the universe, points:

| Stage | names/month | 3M | 6M | 3M hit rate |
|---|---|---|---|---|
| Stage 2 | 369 | +1.05 | **+3.05** | 69% |
| S2 Candidate | 307 | +0.69 | +1.93 | 70% |
| Stage 1 | 98 | −0.44 | +0.39 | 43% |
| Stage 3 | 287 | −0.05 | −0.76 | 54% |
| Stage 4 | 500 | −2.35 | **−4.79** | **15%** |

This matches the only large systematic test found (Roskill, SSRN 2026, S&P 500
1992-2026): Stage 2 earns about +2.3%/yr over the market, which is what a rising
30-week average alone delivers; distinguishing Stage 1 from Stage 3 adds nothing.

## 2. But the P3 timing score pointed the wrong way on two of its parts

Universe-wide, 6M forward excess:

| Stage 2 + S2C, by extension above MA150 | 6M |
|---|---|
| < 10% | +1.18 |
| 10-25% | +2.87 |
| 25-50% | +2.63 |
| 50-75% | +5.68 |
| > 75% | **+6.34** |

| Stage 2 + S2C, by advance age (sessions) | 6M |
|---|---|
| ≤ 30 | +1.06 |
| 31-90 | +1.65 |
| 91-180 | +3.78 |
| 181-365 | **+4.64** |

| RS rating 1-month change | 6M |
|---|---|
| fell > 15 | −0.76 |
| flat ± 5 | +0.13 |
| rose > 15 | +0.37 (hit 42%) |

The timing score **penalised** extension (20% of it), which is the direction that
earned the most, and **rewarded** RS change (20%), which is noise. Persistence,
not freshness, carried the return -- consistent with George & Hwang (2004): names
near their highs keep outperforming and do not reverse.

## 3. "Bonus when it enters Stage 2" -- tested directly

Stocks in Stage 2 now, by their stage one month earlier (universe, 6M excess):

| came from | names/month | 6M |
|---|---|---|
| already Stage 2 | 239 | **+3.41** |
| S2 Candidate (re-entry) | 110 | +2.57 |
| Stage 3 | 17 | −0.58 |
| Stage 1 (the classic base breakout) | 4 | −1.98 |

Entering Stage 2 is not a better moment than being in it. As a rank bonus inside
the model's top 20:

| fresh-Stage-2 bonus (≤30 days) | DISCOVERY vs T0 | CONFIRM vs T0 |
|---|---|---|
| +1 point, monthly | −2.4 pp/yr | −1.6 pp/yr |
| +3 points, monthly | −3.2 | −3.5 |
| +5 points, monthly | **−11.5** (t −2.5) | −6.7 |
| +3 points, quarterly hold | −1.1 | −1.1 |

Negative in both halves, at both horizons.

## 4. What the P3 blend actually swapped

Research top 20 against the 20% blend's top 20, next-month excess:

| DISCOVERY | names/month | excess | value pct | in S2 | in S2C |
|---|---|---|---|---|---|
| dropped by timing | 7.4 | **+2.57%** | P83 | 27% | 54% |
| added by timing | 7.4 | +1.47% | P66 | 97% | 3% |

| CONFIRM | names/month | excess | value pct | in S2 | in S2C |
|---|---|---|---|---|---|
| dropped by timing | 9.1 | **+1.51%** | P90 | 30% | 47% |
| added by timing | 9.1 | +0.96% | P77 | 97% | 3% |

The mechanism, the same in both halves: the blend removed **cheap, high-quality
names pulling back** and added **dearer names in clean Stage 2**. Over one month
the pullbacks bounce (short-term reversal), so every swap cost about a point,
on 7-9 of 20 names, every month, plus the cost of trading them. It is P2's lesson
again: the value block is this model's most reliable, and a trend tilt trades it
away.

## 5. Horizon matters: at 3-6 months stage does separate the top 50

Research top 50, forward excess (2018-11 to 2026-03):

| | 3M | 6M |
|---|---|---|
| Stage 2 | +4.13 | +6.94 |
| S2 Candidate | +1.65 | +5.81 |
| Stage 3 | +0.63 | −1.00 |
| Stage 4 | −1.49 | −1.28 |
| below MA150 | +0.91 | −1.15 |
| > 50% above MA150 | +9.68 | **+13.43** |

Short-term reversal, medium-term momentum. The monthly P3 rotation measured the
first; a positional holder lives in the second. So quarterly-hold variants were
searched on DISCOVERY:

| quarterly top 20, vs T0 | DISCOVERY | CONFIRM |
|---|---|---|
| exclude Stage 3/4 | −0.1 pp/yr | **−3.9** |
| exclude S3/S4 and below MA150 | −0.1 | −3.9 |
| Stage 2 bonus +3 | +1.2 | +0.5 |
| uptrend (S2 or S2C) bonus +3 | +1.0 | −3.2 |
| fresh-S2 bonus +3 | −1.1 | −1.1 |

The Stage 2 bonus is the only rule positive in both halves, and it is noise:
non-overlapping t = +0.27 (DISCOVERY) and +0.13 (CONFIRM), better in 52% and 49%
of quarters, 5-6 names swapped a quarter -- enough trading to consume +0.5 points.
The bucket table and the exclusion rule disagree because the Stage 3/4 names
that reach the top 20 are rare and are the model's highest-conviction value
calls; the ones replacing them were not better.

## Conclusion

1. **No stage rule improves this model's ranking**, at a monthly or a quarterly
   horizon, including a bonus for entering Stage 2. `TIMING_WEIGHT` stays 0 and
   the rank is unchanged.
2. **The model already encodes trend.** 63% of its top 50 is in Stage 2 and 29% in
   S2 Candidate; Stage 3/4 together are 7%. The momentum block (25%) is doing
   the job stage analysis would do.
3. **Stage is still worth showing.** Universe-wide it separates winners from
   losers (Stage 4 beat the market in 15% of months); for a name *outside* the
   model's top list it is real information.
4. **The entry labels were changed from advice to description.** "WAIT ·
   extended" told the reader to wait on the best-performing group in the top 50,
   and "AVOID · Stage 4" is not robust inside it (excluding Stage 3/4 cost 3.9
   points a year in CONFIRM). Labels now read "Stage 2 · uptrend", "Stage 2 ·
   pullback", "Stage 3 · topping", and so on.
5. A pullback in a top-ranked stock (VENUSREM's S2 Candidate) is **not** a
   warning: pullbacks inside the top 50 returned +5.8 points over 6M, close to
   Stage 2's +6.9, and over one month they out-earned Stage 2.

## Still open

* Stage as a portfolio-level **abstention** rule (cash when few names are in
  Stage 2), which a top-20-always backtest cannot see.
* A rule that uses stage for **exits** rather than entries.
* The same questions on a genuinely unseen period: live runs from 2026-09.

## Sources

* Roskill, D., *Does Weinstein Stage Analysis Beat a Moving Average?*, SSRN
  abstract 7429238 (2026).
* George, T. J. and Hwang, C.-Y., *The 52-Week High and Momentum Investing*,
  Journal of Finance 59(5), 2004.
* *Which Momentum?*, ten momentum definitions on NSE top-500, 2009-2026
  (calm.substack.com).
* Bulkowski, T., *Four Stages of Price Movement* (thepatternsite.com): 884 of the
  author's own trades, 1987-2010 -- practitioner evidence, not a systematic test.
