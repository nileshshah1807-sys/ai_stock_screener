# Model methodology and evidence audit

Last reviewed: 2026-08-08
Active model version: 3.0.0

## What the output means

`Final_Score` and `Rating` are deterministic research-ranking heuristics. They
are not estimates of expected return, probability of profit, fair value, or a
SEBI-regulated recommendation. The labels remain useful for preserving the
existing workflow, but the application explicitly exports
`Model_Validation_Status = Research model; point-in-time out-of-sample
validation pending`.

Research can support a variable's economic relevance or an indicator's
definition. It cannot prove this application's exact point grids, 70/30 blend,
15% transcript weight, DCF assumptions, or rating cut-offs. Those parameters
remain **heuristic** until the versioned model produces enough genuinely
out-of-sample observations, including delisted names, benchmark returns,
transaction costs, and no look-ahead data.

## Data-source boundary

- The NSE symbol universe and monthly liquidity category/impact-cost file are
  exchange sources. The impact-cost file is cached and its date, URL and stale
  state are exported.
- Daily OHLCV and company fundamentals come through Yahoo Finance/yfinance,
  which is a convenient free secondary feed without an exchange-data SLA.
  Fundamentals are cached for seven days and can be revised, so they are not a
  historical point-in-time database. Unadjusted close is used for actual traded
  value; split/dividend-adjusted OHLC is used for returns and indicators.
- Transcript discovery starts from NSE corporate filings. Parsed text and
  derived NLP output are cached in Supabase by a separate worker so the daily
  scan performs a bulk lookup rather than per-company document analysis.
- VIGIL is a free secondary aggregation of exchange/regulatory records. Its
  evidence remains shadow-only and requires confirmation against the original
  filing before any future live policy.
- The free application has no reliable point-in-time analyst-consensus and
  estimate-revision history. Earnings-surprise/consensus is therefore absent,
  not silently approximated. News keywords and the FII/DII placeholder do not
  enter the score.

## Logic ledger

| Component | Application policy | Evidence assessment |
|---|---|---|
| Fundamental value, profitability and investment | PE/PB, profitability, leverage, growth and sector-relative ranks contribute to the fundamental score; financial firms use dedicated models. | **Concept supported; exact weights heuristic.** Fama and French document value, profitability and investment patterns. Novy-Marx documents gross profitability. Comparing like businesses is economically preferable to applying industrial leverage ratios to banks, but this app's score grid has not been return-validated. |
| Data quality and anomalies | Missing key fundamentals prevent positive labels; extreme PE/profitability/growth observations are flagged and can cap conviction. | **Defensive control.** It avoids turning absent or obviously exceptional data into positive evidence. Thresholds are operational guardrails, not alpha claims. |
| Trend and momentum | MA50 slope, three-month return, MA alignment, MACD, RSI, StochRSI and ADX/+DI/-DI describe trend state; BUY requires a constructive trend by default. | **Concept supported; combination heuristic.** Momentum is documented over intermediate horizons. ADX measures strength, not direction, so the implementation checks +DI versus -DI. Technical patterns can add information but require systematic out-of-sample evaluation. |
| Price-volume demand proxy | Standard 21-session Chaikin Money Flow plus 20-day price return labels accumulation, distribution, mixed, or unavailable. High relative volume receives bullish points only with an accumulation label. | **Definition supported; predictive use deliberately limited.** CMF describes accumulation/distribution pressure but cannot identify the buyer. Published evidence does not justify treating high volume alone as guaranteed future return. The label is descriptive and has no standalone rating weight. |
| Transcript sentiment and guidance | A fresh, current-cycle call can contribute up to 15%; weak technical confirmation blocks upside weight, while lowered guidance/high risk may still reduce conviction. No transcript is neutral. | **Information content supported; exact NLP score/15% weight heuristic.** Research finds management tone/guidance can contain information, but optimistic tone can also reflect impression management. Calls therefore confirm rather than independently admit a company, old calls become prior-cycle context, and downside is asymmetric. |
| Reverse DCF | Solves for market-implied cash-flow/terminal-growth assumptions and adds at most the configured 10% when the cash-flow proxy is valid. It is disabled for financials and real estate with inadequate inputs. | **Valuation framework supported; assumptions are scenarios.** Present-value valuation and terminal assumptions are standard, but discount rate, sector growth benchmarks and Yahoo cash-flow data are not forecasts. Output is labelled market-implied/scenario analysis. |
| Liquidity and execution | NSE Group I/II/III and mean impact cost for a Rs1 lakh order are primary. A 1% median-turnover participation proxy is used for larger/custom positions or unavailable official impact values. Liquidity does not modify score/rating; the execution-aware report rank is separate from `Investment_Rank`. | **Official definition for the reference order; extrapolation heuristic.** NSE/SEBI define Group I as at least 80% trading frequency and no more than 1% mean impact cost for a Rs1 lakh order. Build capacity above that size is only a conservative planning proxy, not a market-impact forecast. |
| Exchange/issuer red flags | Credit-default, pledge/encumbrance and exchange-surveillance evidence is cached and shown as shadow counterfactuals. | **Risk relevance supported; automated severity policy not validated.** VIGIL is a convenient free aggregation rather than the primary exchange filing. Nothing changes live score/rating until the underlying NSE/SEBI/issuer evidence is confirmed. |
| News and FII/DII | Headline sentiment is displayed for top rows; FII/DII is logged. | **Experimental/display-only.** Neither is an active score input. The FII/DII implementation is explicitly a placeholder. |
| Versioned outcome log | Each run stores model version and later realized prices. Performance summaries exclude observations from other model versions. | **Necessary but not yet sufficient.** Absolute return averages are monitoring diagnostics; a proper evaluation still needs benchmark-relative, survivorship-free, point-in-time results and costs. |

## Primary and research sources

### Liquidity and market execution

- [NSE: Impact Cost](https://www.nseindia.com/static/products-services/indices-impact-cost) defines impact cost as an order-size-dependent measure of execution/liquidity.
- [NSE security categorisation circular](https://nsearchives.nseindia.com/content/circulars/cmpt5868.htm) and the [SEBI categorisation annexure](https://www.sebi.gov.in/sebi_data/commondocs/ann4mast_p.pdf) specify the six-month frequency and Rs1 lakh mean-impact-cost tests: Group I requires trading on at least 80% of days and impact cost no greater than 1%.
- [NSE Margin Trading Facility FAQ](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/FAQs%20on%20Margin%20Trading%20Facility_0.pdf) documents the exchange security-category file and Group I eligibility.

### Fundamentals and valuation

- [Fama and French, *A five-factor asset pricing model*](https://www.sciencedirect.com/science/article/pii/S0304405X14002323/pdf) documents value, profitability and investment-related return patterns.
- [Novy-Marx, *The Other Side of Value: The Gross Profitability Premium*](https://oldschoolvalue-files.s3.amazonaws.com/pdf/Novy-Marx_Gross-Profitability-Anomaly_JFE_2013.pdf) documents the relation between profitability and average returns.
- [CFA Institute, *Equity Valuation: Concepts and Basic Tools*](https://rpc.cfainstitute.org/research/foundation/2024/valuation-handbook-2023) describes present-value valuation and the uncertainty in required-return assumptions.
- [Damodaran, *Growth and Terminal Value*](https://www.stern.nyu.edu/~adamodar/pdfiles/ovhds/dam2ed/growthandtermvalue.pdf) explains the sensitivity of DCF value to growth and terminal-value assumptions.

### Technical and volume evidence

- [Jegadeesh and Titman, *Returns to Buying Winners and Selling Losers*](https://www.jstor.org/stable/2328882) documents intermediate-horizon return continuation; it does not validate this application's thresholds.
- [Lo, Mamaysky and Wang, NBER Working Paper 7613](https://www.nber.org/papers/w7613) finds that some systematically recognized technical patterns can provide incremental information while emphasizing the need for objective methods.
- [Fidelity: Average Directional Index](https://www.fidelity.com/viewpoints/active-investor/average-directional-index-adx) explains that ADX measures trend strength and +DI/-DI indicate direction.
- [Fidelity: Chaikin Money Flow](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/cmf) gives the standard CMF construction and its accumulation/distribution interpretation.
- [Lee and Swaminathan, *Price Momentum and Trading Volume*](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00280) shows that volume interacts with momentum; it does not support equating turnover with demand or guaranteed returns.

### Management communication

- [Huang, Teoh and Zhang, *Tone Management*](https://www.hks.harvard.edu/centers/mrcbg/publications/fwp/2015-05) reports that abnormal management tone is associated with future earnings, uncertainty and delayed market reaction.
- [Davis, Ge, Matsumoto and Zhang, *The Effect of Manager-Specific Optimism on the Tone of Earnings Conference Calls*](https://www.sciencedirect.com/science/article/abs/pii/S0378426611002901) supports studying call tone while showing that manager style matters.
- [*Managerial Ability and Stock Price Crash Risk*](https://doi.org/10.1007/s10551-019-04326-1) is evidence that optimistic disclosure can coexist with impression-management/crash-risk concerns.
- [*A Catering Theory of Earnings Guidance*](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/catering-theory-of-earnings-guidance-empirical-evidence-and-stock-market-implications/78F476FCE3B34CD72257F526A7A754EF) cautions that guidance decisions can respond to market incentives.

## Validation protocol before calling the model successful

1. Freeze each material logic change under a new `MODEL_VERSION`; never mix its
   outcomes with older versions.
2. Save the complete daily eligible universe and inputs as known on that date,
   including unavailable data and later delistings. Do not rebuild history with
   today's constituents or restated fundamentals.
3. Measure 1-, 3-, 6- and 12-month total returns against Nifty broad-market and
   size-appropriate benchmarks. Include plausible entry slippage, impact cost,
   brokerage, taxes and multi-day builds.
4. Compare rating buckets and deciles for monotonicity, drawdown, hit rate,
   turnover and capacity. Report confidence intervals; do not optimize on one
   period and call the same period a test.
5. Use a walk-forward holdout. Promote a heuristic to a claimed predictive
   rule only after it survives multiple market regimes and remains useful after
   costs.

Until those conditions are met, the application is working as an auditable
research screener—not as a proven return-generation model.
