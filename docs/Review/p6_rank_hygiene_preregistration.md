# P6 pre-registration: do data-anomaly and illiquid names earn their place at the top?

Written **before** any variant's returns were computed, for the same reason as
P1-P5. Condition 8 of the validation protocol in `docs/model_methodology.md`.

Author: research session, 2026-09-25. Branch `feat/returns-calculator` follows
`main` at `a9bdb0a`; this study changes no production code.

## The observations that motivate it

From the 2026-09-24 NSE production run (2,309 ranked names):

| | Anomaly-flagged | Median turnover < Rs 20 lakh | Median market cap |
|---|---|---|---|
| Top 20 | **30%** | 5% | Rs 936 Cr |
| Top 50 | 20% | 8% | Rs 1,401 Cr |
| Universe | 11.5% | 24% | Rs 2,027 Cr |

1. **Anomaly-flagged names are ~2.6x over-represented at the top.** The dominant
   flag is "extreme earnings growth" (EPS up more than 200% year on year). A
   one-off earnings jump -- a debt write-back, an asset sale -- enters twice:
   as a high `Earnings_Yield` in the value block and as high EPS growth in the
   growth block. GAYAPROJ ranked 6th with a trailing PE of 0.21, an earnings
   yield of 484%, ROA above 50% and a margin above 100%. The flag caps the
   *rating*; `Investment_Rank` ignores it.
2. **The live universe is not the validated universe.** Every P0-P5 result
   used a Rs 20 lakh median-turnover floor. Production runs with
   `PREFILTER_RESEARCH_UNIVERSE_BY_LIQUIDITY=False`, so a quarter of the
   ranked universe sits below that floor, and the cross-sectional percentiles
   are computed over a different population from the one the weights were
   fitted on. AHLWEST ranked 3rd at a Rs 2.4 lakh median daily turnover.

## Hypotheses

* **H1 (earnings spike).** Top-20 names whose latest earnings are a spike
  underperform the rest of the top 20; replacing them with the next names
  improves the top 20.
* **H2 (liquidity parity).** Ranking over the full universe (no turnover floor)
  and then holding the top 20 does worse, net of the backtest's impact model,
  than ranking over the Rs 20 lakh universe.
* **H3 (fresh break at entry).** Added 2026-09-25 at the reader's prompt, still
  before any result was computed. P5 found that *selling* a holding the session
  after it breaks into Stage 3 or 4 improved risk-adjusted return; P4 found that
  excluding *every* Stage 3/4 name at purchase cost return, because most of them
  are cheap names in a long pullback. The untested middle is the entry mirror of
  the P5 exit: do not buy a top-20 name whose Stage 3/4 run began within the
  last 21 sessions. The rationale is that the market has just started pricing a
  deterioration the annual statements cannot yet show.

## Definitions, fixed now

* **Panels.** Point-in-time Model 5 cross-sections from `backtest/`, monthly,
  2018-11 to 2026-08, built twice with the runner's universe rule: turnover floor
  0 (production-like) and Rs 20 lakh (the validated rule). Everything else as in
  `tools/build_research_panel.py`.
* **Spike flag (H1).** The archive has no vendor `Earnings_Growth`, so the
  statement analogue of production's flags: latest annual EPS more than 3x the
  prior year's (growth above 200%) *or* earnings yield above 50% (PE below 2).
  If the panel lacks the inputs for this, H1 is reported as untestable rather
  than approximated some other way chosen after looking.
* **Selection.** Top 20 by `Research_Score`, equal weight, next-session entry,
  1-month hold, the runner's costs. Variants replace excluded names with the
  next-ranked eligible names, so every variant holds 20.

| Variant | Panel | Rule |
|---|---|---|
| **B0** | Rs 20 lakh | baseline, the validated configuration |
| **H1-X** | Rs 20 lakh | B0, excluding spike-flagged names |
| **F0** | floor 0 | production-like ranking |
| **F0-L** | floor 0 | F0, skipping names below Rs 20 lakh *after* ranking |
| **H3-X** | Rs 20 lakh | B0, excluding names in Stage 3 or 4 with `Days_In_Stage` <= 21 |

H3-X is judged against B0 by the same rule below, and additionally on 3-month
forward excess (the P4 horizon at which stage separated the top 50), where it
must also not be worse in either window.

## Windows

DISCOVERY 2018-11 to 2022-12, CONFIRM 2023-01 to 2026-08, as in P4/P5. Neither
is pristine: every window has been seen in earlier studies. This measures a new
selection rule on seen data, which is weaker evidence than an unseen period.

## Decision rule, fixed in advance

A variant is recommended only if, **in both windows**, its mean monthly top-20
excess return over its own panel's equal-weight universe beats the comparison
by at least **0.10 points a month**, net of costs, and its worst month is not
worse by more than 2 points. Comparisons: H1-X against B0; F0 and F0-L against
B0.

For H1, the spike-flagged names are also reported on their own (mean next-month
excess, count per month). If they are fewer than one a month on average, the
result is reported as too thin to act on, whichever way it points.

# Result, recorded 2026-09-25

Panels: floor 0, 152,593 rows (~1,635 names a month, 25.5% below Rs 20 lakh);
Rs 20 lakh, 113,652 rows (~1,276 a month). 93 monthly rebalances with 1M
returns (50 DISCOVERY, 43 CONFIRM). Weights confirmed 5.1 (Q 0.25, G 0.20,
V 0.25, M 0.25, R 0.05).

## A cost-model caveat that shapes the reading

The pre-registered metric is the runner's `Net_Return_1M_Pct`, which charges a
full round trip on every holding every month. Actual top-20 turnover is ~33% a
month, so that metric overstates costs roughly threefold. Every comparison is
therefore also reported with costs charged only on names actually bought or
sold ("turnover-aware"). **The verdicts below use the pre-registered metric**;
the second is shown so the reader can see whether the conclusion depends on
the cost convention. For every variant it does not.

## Mean monthly top-20 excess over the panel's equal-weight universe, points

| Variant | DISC runner | CONF runner | DISC turnover-aware | CONF turnover-aware |
|---|---|---|---|---|
| **B0** Rs 20 lakh baseline | +0.46 | +0.24 | **+1.54** (t 2.2) | **+1.15** (t 1.7) |
| H1-X exclude earnings spikes | +0.01 | −0.17 | +1.01 | +0.69 |
| H3-X exclude fresh S3/S4 break | +0.46 | +0.30 | +1.49 | +1.18 |
| F0 floor 0 (production-like) | +0.03 | +0.00 | +1.59 | +1.17 |
| F0-L floor 0, skip < Rs 20 lakh | −0.31 | +0.02 | +0.80 | +0.92 |

At 3 months (runner costs) B0 earns +4.75 (t 4.2) and +2.76 (t 2.9) over the
universe: the ranking is stronger over a quarter than over a month.

## Against the rule

| Variant vs B0 | DISC | CONF | Worst month | Result |
|---|---|---|---|---|
| H1-X | −0.44 | −0.41 | worse (−0.9, −3.1) | **refuted** |
| H3-X, 1M | −0.00 | +0.06 | not worse | **fails** (below +0.10 in both) |
| H3-X, 3M | −0.06 | −0.35 | mixed | fails |
| F0 | lower excess in both (runner); equal (turnover-aware) | | | not better than B0 |
| F0-L | lower in both | | | not better than B0 |

## H1: the earnings-spike names are the model's lottery tickets

Spike-flagged names are 4.2 (DISC) and 3.5 (CONF) of the top 20 a month -- the
top of the list over-represents them historically, as it does today. Their mean
next-month excess is **+2.48 / +3.64** against −0.12 / −0.16 for the rest of the
top 20, and at 3 months +9.5 / +9.7 against +3.4 / +2.0. But the median is no
better (−3.04 vs −1.76 in DISC; −0.30 vs −1.72 in CONF) and the hit rate is
similar; removing the five best name-months per window takes the flagged mean
to about the rest's. A few multi-baggers carry them. Excluding them removes the
multi-baggers, which is why H1-X loses in both windows.

Split (exploratory, not pre-registered): names with PE below 2 were positive in
both windows (+4.25, +1.65); EPS jumps without a sub-2 PE flipped sign
(−1.15, +3.14).

What the archive cannot test: it is built from as-filed XBRL, so a sub-2 PE in
it is a real reported profit. Production's anomaly flags come from the vendor
feed, where "margin above 100%" can be a data error rather than an event. This
study says nothing about vendor errors.

## H3: fresh breaks do underperform, but too rarely to move the portfolio

Names whose Stage 3/4 run began within 21 sessions are 1.0 and 1.3 of the top 20
a month. Individually they lag: −0.99 / −0.60 against +0.39 / +0.24 for the rest,
and −3.7 / −4.0 once the five best name-months are removed; the CONFIRM hit rate
is 36% against 46%. Replacing one name a month with the 21st moves the portfolio
by +0.03 to +0.06 points a month at 1M and −0.06 / −0.35 at 3M. Below the
pre-registered bar in both windows. Consistent with P5: stage information is
real but belongs in the *holding* decision (the exit alert), not the rank.

## H2: the liquidity mismatch is a capacity question, not a return one

Top-20 net return, same months, turnover-aware: F0 +4.27 / +3.11 a month against
B0 +3.75 / +3.03 (difference t +1.0 / +0.6). At the runner's Rs 1 lakh position
the illiquid names paid for their impact cost. Under the runner's full-round-trip
convention F0 lags B0, because the illiquid names carry ~10-12% round-trip costs
against ~1.3-1.7% for the rest. Neither result argues that the production
universe loses money at Rs 1 lakh a name; both argue that it cannot scale.

## What this means

1. No change to the ranking. H1 and H3 fail; F0 is not worse than B0 at the
   tested size.
2. The anomaly flag stays a label. Vendor data errors (PE below 1 from a bad
   EPS, margin above 100%) are a separate hygiene question this archive cannot
   answer; they need a check against the filed statement, not a rank rule.
3. Position size is the open risk. A reader deploying more than ~Rs 1 lakh a name
   should read `Actionable_Rank`, not `Investment_Rank`.
4. Caveats as declared: both windows were seen in earlier studies, the spike and
   fresh-break samples are 100-370 name-months, and the means are tail-driven.
