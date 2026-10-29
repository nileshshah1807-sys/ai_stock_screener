# Running themes (Jim)

_Last updated 2026-10-25. Consensus, dissent, conflicts, and what it could mean for Winnow's scoring.
Opinions are attributed; "Jim:" marks my analysis. Research notes only, not investment advice._

## 1. India: correction driven by oil, yields and FII selling
- **Consensus:** Nifty ~14% off peak (22,600 on 23 Oct); causes named by nearly every source: Brent >$110, US 10y ~5%, rupee at record lows, RBI's first hike since 2023, steady FII selling while DIIs buy.
- **Dissent:** sabharwal (X) and Salman see the setup as improving / 2013-like (a grind, then a big recovery); Rao (Zerodha) won't write off the uptrend. Karan Shah: it depends on whether the "floors" (DII/SIP flows etc.) hold.
- **Conflict:** FII 2026 selling is ₹3.1 lakh cr (NSDL, news) vs ">₹4.1 lakh cr" (Salman; Scientific Investing comment). Jim: likely exchange "cash market" provisional figures vs NSDL net (which nets primary-market buying). Do not quote either without naming the basis.

## 2. Breadth flipped: small caps led, then broke
- Microcap 250 was +19% YTD in Sept while Nifty fell; small caps then dropped >7% in the week to 23 Oct. Salman and Saurabh read the earlier pattern as a stock picker's market; Llama/Zerodha flag the speed of the reversal.

## 3. Earnings dispersion, not a uniform downgrade
- MarketSmith: widest dispersion in seven quarters; upgrades in banks/NBFCs/telecom/capital goods, downgrades in IT, staples, downstream oil.
- Saurabh: the market pays for sales growth >~20% at any multiple and punishes low growth at any multiple.
- Lotiya: FIIs rotate by sector, healthcare the one persistent buy; pharma/metals the only double-digit gainers (Zerodha).

## 4. US: earnings strong but narrow; stock-bond hedge broken
- Innes: 27% expected Q3 EPS growth, 68% from 10 firms. Roberts: oil-driven inflation made stocks and bonds fall together; tech oversold, energy crowded.

## What could improve Winnow's scoring (Jim's proposals, each needs a pre-registered backtest)
Each is a candidate study, not a change. Per the P10 lesson, the base must be `model_5`.
1. **Earnings surprise from filings (PEAD).** The literature (Bernard-Thomas; revenue-surprise papers) finds drift is stronger when revenue and profit surprise the same way. We already store each NSE quarterly filing minutes after it lands, and `backtest.fundamentals.QuarterPanel` is point-in-time. Study: a standardised YoY surprise (profit and revenue, same basis), and whether "both beat" ranks better than `Revenue_Growth`/`Earnings_Growth` alone. Fits as a fundamental component; no market branch.
2. **Revision breadth as the dispersion signal.** We have no analyst estimates, so an estimate-revision factor is out of reach. Proxy worth testing: the change in a company's own growth rate quarter to quarter (acceleration), which is what upgrade/downgrade cycles track.
3. **Momentum crash control.** P10's vol-scaling failed on the gated base. The 52-week-high distance ("high-to-price") score is a different crash fix that was not tested; we already compute the prior-year high for `market_breadth_levels`. Study against `model_5`, judged on drawdown in 2020 and the Oct 2026 small-cap break.
4. **Growth regime.** Saurabh's claim (growth rewarded regardless of valuation in 2026) is testable on our archive: return spread by sales-growth tercile within valuation tercile, 2026 vs history. If it holds only in 2026 it is a regime, not a rule, and should not change weights.
5. **Concall tone.** Papers reviewed in the ACM 2026 study note *overly optimistic* tone is followed by weaker returns. Our outlook stance ranks a call against the median call; worth checking whether the top band (bullish ≥78) underperforms the optimistic band. Needs the Molinaro paper (SSRN, unread).
6. **FII holding change.** `shareholding_patterns` already stores FII % per quarter. FIIs rotate by sector (Lotiya); a study of FII-change vs next-quarter return would show whether it earns a place beyond display.
- **Not proposed:** macro (oil, yields, RBI) inputs. Scoring is cross-sectional within a run and must stay market-agnostic (CLAUDE.md); macro belongs in research notes, not scores.

## Pursue next session
- Read the three blocked sources (WisdomTree, NSE momentum whitepaper, SSRN Molinaro).
- Q2 FY27 results so far: post-results brokerage upgrade/downgrade tallies (Motilal, Kotak, JM).
- US: Fed decision 28 Oct, Microsoft/Alphabet/Amazon results; check whether the tech "oversold" call held.
- Find sources on 52-week-high momentum in India and on PEAD in Indian stocks.

## Sector and industry relative strength (god's request, 29 Oct 2026; work id sector-rs-research)
_Research only. Confidence H/M/L as in the log. "Jim:" = my analysis._

**Bottom line (Jim):** group momentum is a real, published effect in the US, and Indian studies find momentum present across industries. But nobody I found has measured "India is 80% top-down". The best-known figures are US ones from the 1950s-60s and put sector + industry at 12-49% of a stock's move, not 80%. A point-in-time NSE label map can be partly rebuilt from archived Nifty 500 lists, so the backtest blocker is partly removable. The test is worth running, under a strict kill rule.

### 1. Evidence
- **US, industry momentum:** Moskowitz & Grinblatt (Journal of Finance 54(4), 1999): a strong momentum effect in industry components of returns "accounts for much of" individual-stock momentum; stock momentum is "significantly less profitable" once industry momentum is controlled for. [abstract](https://ideas.repec.org/a/bla/jfinan/v54y1999i4p1249-1290.html). **H** (abstract read; tables not).
- Disputed in part: Grundy & Martin (2001) contest how strong that conclusion is; a Canadian study finds industry does not explain momentum there; Arnott, Clements, Kalesnik & Linnainmaa find industry momentum strongest at a one-month lag and subsumed by factor momentum. Seen via search summaries only, papers not opened. **M**.
- **Sector rotation:** Faber (SSRN 1585517) via [Quantpedia](https://quantpedia.com/strategies/sector-momentum-rotational-system): top 3 of 10 US sectors by 12-month return, monthly, 1928-2009: 13.94% a year vs ~10% buy-and-hold, max drawdown -46%, before costs, turnover 100-400%. **M** (secondary page).
- **India:** Garg & Varshney, *Global Business Review* 16(3) 2015, 2000-2013: momentum returns are robust "in various industries" ([RePEc](https://ideas.repec.org/a/sae/globus/v16y2015i3p494-510.html)). That is momentum *within* industries, not industry-level momentum predicting stock returns. **M**. I found no Indian test of Moskowitz-Grinblatt and no published Indian sector-rotation backtest with costs. Practitioner repos and guides ([fnotrader](https://www.fnotrader.com/blog/sector-rotation-india), [GitHub](https://github.com/RaajitSingh1306/Nifty-Sector-Rotation)) give designs, not results.
- **The "80% top-down" claim:** no measured source found. Traced origins:
  - MarketSmith India / William O'Neil + Co.: "roughly half" of a stock's move comes from its group; a MarketSmith India blog post (unreachable to me) puts it at 37% industry group + 12% sector. No study is named. **L** for the number.
  - Brealey (1969), 63 US stocks in 6 industries, 1952-60: market 31%, company 20%, industry 12%, other 37% ([Bulkowski](https://www.thepatternsite.com/factors.html)). **M**.
  - King (1966, *Journal of Business*): market and industry factors explain most co-movement; the exact shares were not visible. **M**.
  - India: an arXiv study of the NSE correlation matrix ([0704.2115](https://arxiv.org/pdf/0704.2115)) finds weaker sector grouping than the NYSE. That argues against a strong top-down claim. **M** (abstract-level).
  - Jim: if anything, the "80%" likely bundles market + sector + industry together. The market share alone is ~31-50% in the old US studies.

### 2. How practitioners compute group strength
- **IBD / MarketSmith India:** 197 industry groups ranked 1 (best) to 197, "mainly on six-month price performance", using a proprietary least-squares fit on summed prices of group members ([MarketSmith India groups](https://marketsmithindia.com/mstool/industrygrouplist.jsp)). Stock RS is a separate 1-99 rank over 12 months. Group RS feeds their composite "Master Score". The "Group Rank Up" screen picks groups between the 25th and 55th percentile that rose 15+ places in a week. **M** (pages may be old).
- Open-source IBD-style RS: 12-month return with the latest quarter double-weighted, ranked to a percentile ([skyte/relative-strength](https://github.com/skyte/relative-strength)). **M**.
- Sector rotation: 3-12 month returns, Mansfield RS, risk-adjusted momentum or distance from the 52-week high; hold the top 3 groups; rebalance monthly or quarterly, where cost drives the difference. **M**.
- **Median vs cap weight:** Moskowitz-Grinblatt and Faber use cap-weighted indices. IBD's summed prices are price-weighted. Winnow's own `RS_Sector_6M_Pct` already uses the median, "so one runaway constituent cannot define its whole sector's baseline" (`screener/factors.py`). Jim: use the median, as Winnow already does. Cap weights let one heavyweight (Reliance, HDFC Bank) define a group.
- **Sector and industry used together:** O'Neil-style work ranks the industry group first and the sector second. The 37/12 split above is their claim of relative weight. No source tests both levels jointly.

### 3. Point-in-time classification data
- **NSE structure:** 4 levels: 12 macro-sectors, 22 sectors, 59 industries, 197 basic industries ([niftyindices](https://niftyindices.com/resources/industry-classification)). It was harmonised with BSE from 31 Mar 2022 (then 58 industries, 200 basic industries; [press release](https://www.niftyindices.com/Press_Release/ind_prs21032022_1.pdf)). Companies are classified by revenue. NSE publishes no change log that I found. **H** for the structure.
- **Archived Nifty 500 lists (Wayback Machine), checked 29 Oct 2026:** snapshots with Company, Industry, Symbol, ISIN exist for Oct 2018, Feb 2019, Jul 2020, May 2022, Oct 2022, Apr 2023, Feb 2024, Jun 2025, Aug 2025, and Jan, May, Aug, Sep and Oct 2026. The 2018 file uses old coarse labels (e.g. SERVICES, IT), which a delisted name like 8K Miles still carries. **H** (fetched the CDX index and the 2018 file).
  - Gaps: Feb 2019 to Jul 2020 and Jul 2020 to May 2022. The file covers Nifty 500 members only. The taxonomy changed in 2022, so only a coarse ~20-group level is consistent across the whole period.
- **Mutual fund monthly portfolios** (SEBI-mandated) list each holding's industry by ISIN, month by month, including later-delisted names. This is point-in-time but only for held stocks, and it means collecting files from every fund house. **M** (known practice, not fetched).
- BSE's scrip list carries industry for delisted scrips too. The repo never fetches BSE itself (CLAUDE.md), so this would be owner-run only. **L**.
- Production today takes `Sector`/`Industry` from Yahoo (`screener/data_collection.py:1345`), which has no history. A tested group signal would need production to use the same NSE labels the test used.

### 4. Pre-registered test proposal (for Oscar, against `model_5`)
- **Hypothesis:** stocks in strong groups beat the stocks `model_5` would otherwise pick, after costs.
- **Label map:** each stock's coarse NSE group from the latest Nifty 500 snapshot on or before the signal date. Names with no earlier snapshot take the next one, flagged back-filled. Report results with and without back-filled names.
- **Variables:**
  - `Group_RS_6M` = median 6-month return of the group's members in that month's universe (at least 8 members, as `FACTOR_MIN_SECTOR_PEERS`), minus the benchmark 6-month return.
  - `Group_RS_Rank` = its percentile, 1-99, across stocks.
  - An industry-level version on 2022+ labels is a secondary result, not judged.
- **Variants (two only, to limit multiple testing):**
  - **A, score:** `Group_RS_Rank` enters the momentum block at the same weight as `RS_Sector_6M_Pct`.
  - **B, gate:** stocks in the bottom third of groups cannot enter the Top 20; ranking is otherwise unchanged.
- **Diagnostic (not judged):** the monthly rank correlation of `Group_RS_6M` with next-month stock return, alone and after controlling for the stock's own 6-month return. This is the Moskowitz-Grinblatt question for India.
- **Period:** month-end signals, Dec 2018 - Sep 2026 (the p0 archive), on `reports_advanced/backtest_ext`. Judged on the full period and on each half, Dec 2018 - Sep 2022 and Oct 2022 - Sep 2026.
- **Success:** net CAGR at least 2.0 points above `model_5`, max drawdown no more than 3 points deeper, and better in both halves.
- **Kill rule:**
  - the map covers less than 85% of universe stock-months; or
  - any success test fails; or
  - more than half the excess return comes from one group; or
  - the result flips sign once back-filled names are removed.
- Jim: the bar is high on purpose. The 25 Oct momentum variants all failed, and this is another momentum signal.
