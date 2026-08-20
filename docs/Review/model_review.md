Research review of Model 5.0

I reviewed the architecture and methodology you shared, then compared it with established factor-index construction, reverse-DCF practices, liquidity methodology, and backtesting requirements. My conclusion is that Model 5.0 is a thoughtfully engineered research-ranking system, but it is not yet reliable enough to treat BUY or STRONG BUY as a validated return prediction.

Executive assessment
Current reliability by purpose
Purpose	Reliability	AssessmentData collection and auditability	8/10	Strong completed-bar controls, cache separation, configuration hashes, evidence periods, coverage fields, and fail-closed behavior
Cross-sectional stock ranking	6/10	Reasonable factor structure, but weights, transformations, sector normalization, and interactions remain unvalidated
Recommendation labels	4/10	BUY and STRONG BUY thresholds are policy labels, not empirically calibrated probabilities
Reverse-DCF valuation	4/10	Useful as supporting evidence, but fixed assumptions and raw cash-flow instability can create misleading upside/downside
Backtested predictive reliability	2/10 currently	Point-in-time fundamentals, delisted companies, publication dates, costs, and genuine out-of-sample tests are still pending
Operational production reliability	8/10	Your full-NSE candidate run demonstrates operational coherence, not investment alpha

The model deserves credit for explicitly making that distinction in its documentation.

1. What Model 5.0 gets right
A. The five-factor structure is defensible

Your combination of:

Quality: 35%
Growth: 20%
Value: 15%
Momentum: 25%
Risk: 5%

is directionally consistent with established multifactor research. Value, momentum, quality, and defensive factors capture different return drivers, and combining them can reduce dependence on one factor cycle. NSE’s own multifactor framework combines momentum, quality, value, and low volatility rather than relying on one metric.

Your use of 6-month and 12-month momentum is also sensible. NSE’s momentum methodologies use 6-month and 12-month returns adjusted for volatility, while professional momentum implementations commonly use relative returns over approximately one to twelve months.

Important improvement

Your momentum factor should be volatility-adjusted, not only percentile-ranked raw relative strength. If not already implemented, consider:

Momentum_6M  = return_6m / annualized_volatility
Momentum_12_1 = return_month_12_to_month_1 / annualized_volatility


Skipping the most recent month can reduce short-term reversal noise. At minimum, test both:

6-month and 12-month total return
6-month and 12-minus-1-month volatility-adjusted return

Do not assume the NSE formula will automatically be optimal for your broader full-NSE universe.

B. Separating evidence score from decision score is excellent

The distinction between:

Evidence_Score
Decision_Score
Investment_Rank
Actionable_Rank

is one of the strongest parts of your design.

It prevents a liquidity limitation, missing transcript, or policy ceiling from pretending that the underlying company evidence changed. Your implementation also correctly recognizes that NSE impact cost represents execution liquidity, not business quality. NSE calculates stock categorization using trading frequency and mean impact cost, with the reference impact measured for a ₹1 lakh order from order-book snapshots.

C. Fail-closed behavior is appropriate

Blocking BUY recommendations when critical bank, NBFC, or insurance data is unavailable is better than assigning neutral values. Likewise, refusing to publish Model 5.0 below 95% statement coverage is a good operational control.

However, this protects against missing-data failures. It does not establish that the surviving scores predict future returns.

2. Main reliability problem: predictive validation is still missing

The most important weakness is exactly what your methodology already acknowledges: the model does not yet have a trustworthy point-in-time validation dataset.

A fundamental backtest must use the value that was known on the historical decision date, including its original publication date. If FY2023 figures were published in May 2024, a January 2024 rebalance cannot use them. Restated values must also not replace the values originally available to investors.

You also need historical universe membership, including:

Delisted companies
Suspended companies
Merged companies
Companies later excluded from NSE
Symbols that changed
Securities with incomplete histories

Testing today’s NSE universe in earlier years creates survivorship bias because failed companies disappear from the test population. Reporting lag and survivorship bias can materially inflate returns and understate drawdowns.

Therefore, do not validate only with “Model 4 versus Model 5 top-20 churn”

That comparison tells you whether the models differ. It does not tell you which one is better.

Your validation should measure forward returns after every historical rebalance:

1-month forward return
3-month forward return
6-month forward return
12-month forward return


And evaluate:

Spearman rank information coefficient
Top-decile minus bottom-decile return
Hit rate against benchmark
CAGR
Maximum drawdown
Sharpe or information ratio
Turnover
Expected transaction cost
Sector and size attribution
Performance during bull, bear, sideways, and reversal regimes

Use walk-forward periods, not random train/test splits.

3. Why a STRONG BUY can show negative DCF upside

This is not necessarily a software bug. It can occur because your factor recommendation and DCF answer different questions.

The factor model asks:

Is this company stronger than other companies in the current universe?

The DCF asks:

Under these cash-flow, growth, terminal-growth, and discount-rate assumptions, is the company worth more than its present enterprise value?

A stock can rank very highly on quality, growth, and momentum while already trading at an expensive valuation. Multifactor quality and momentum strategies can intentionally select strong but highly priced companies. NSE’s recent momentum-quality indexes, for example, can have relatively high aggregate valuation multiples.

So this combination is logically possible:

Excellent business quality
Strong earnings growth
Strong relative momentum
Low accounting risk
Expensive market price
Negative DCF upside


However, if the value factor is only 15%, while quality plus momentum contribute 60%, an expensive compounder can still become STRONG BUY. That is a model policy choice, not necessarily an inconsistency.

My recommendation

A STRONG BUY should require one of these valuation conditions:

Value_Factor_Percentile >= 35
OR
DCF_Base_Upside >= -10%
OR
Reverse_DCF_Expectation_Gap is favorable


Do not require positive DCF upside rigidly because noisy FCF can incorrectly block good companies. But a stock with, for example,-45% base-case upside should not receive STRONG BUY without an explicit “valuation conflict” status.

Suggested classification:

STRONG BUY: strong factor evidence and no major valuation conflict
BUY, EXPENSIVE: strong factors but demanding valuation
HOLD, HIGH QUALITY: strong company but insufficient expected return
VALUE OPPORTUNITY: attractive valuation but weaker momentum
SPECULATIVE: high growth or momentum with weak cash-flow support

These labels communicate the source of the recommendation more honestly than one score.

4. Your “Reverse DCF” may be mixing two different concepts

This is a critical terminology issue.

A genuine reverse DCF begins with the current market enterprise value and solves for the growth, margin, or return-on-invested-capital assumptions embedded in that valuation. It does not normally start with a fixed growth assumption and produce upside.

If your model uses:

Fixed forecast growth
Fixed discount rate
Fixed terminal growth
Current FCF
→ Estimated fair value
→ Base-case upside


that is a standard forward DCF scenario, not a reverse DCF.

A proper reverse DCF would calculate:

Current Enterprise Value
Current normalized FCFF
Discount rate range
Terminal growth assumption
→ Solve for implied FCFF growth


Then it asks whether that implied growth is plausible relative to:

Historical revenue and FCF growth
Reinvestment rate
ROIC
Industry growth
Management guidance
Addressable market
Competitive advantage duration

The distinction matters because “negative base-case upside” comes from a forward valuation assumption, while “implied growth” describes expectations already embedded in the market price.

5. Fixed discount rates are too weak for a full-NSE model

Using one discount rate across all companies will systematically misvalue risk.

A mature consumer company, a leveraged real-estate developer, a cyclical metal producer, and a small software exporter should not have the same required return. DCF valuation is highly sensitive to the discount rate and terminal assumptions, especially because terminal value can represent a large portion of estimated enterprise value.

I recommend a transparent discount-rate grid, not a single pseudo-precise WACC:

Low-risk large company:       10% / 11% / 12%
Normal company:               11% / 12.5% / 14%
Small or cyclical company:    13% / 15% / 17%
High-risk or leveraged firm:  DCF ineligible or 16%+


Classification can use:

Market-cap/liquidity bucket
Net debt/EBITDA
Earnings variability
Cash-flow variability
Sector cyclicality
Interest coverage
Country risk
Beta only as a secondary input

Output a valuation range:

Bear value
Base value
Bull value
Implied growth
Discount-rate sensitivity
Terminal-growth sensitivity


A range is more honest than one base-case upside.

6. Normalize cash flow before valuation

Using the latest annual FCF alone can produce extreme errors when:

Working capital temporarily rises
A company completes a large capex cycle
Commodity prices peak or collapse
Asset sales inflate cash flow
Receivables temporarily reverse
Financial companies are treated like industrial businesses

Instead, calculate a normalized base:

Normalized_FCFF =
median(last 3 years FCFF)
or
weighted average of last 3 to 5 years FCFF


Also compare:

FCF conversion over multiple years
CFO minus maintenance capex
CFO/EBITDA
Working-capital adjustment
Capex versus depreciation
Acquisition-adjusted cash flow

Damodaran’s valuation framework ties sustainable growth to reinvestment and returns on investment rather than treating growth as a free independent input. High terminal growth must eventually converge toward sustainable economic growth, and perpetual growth must remain below the discount rate.

For cyclical sectors, use mid-cycle margins and mid-cycle commodity assumptions. For banks and insurers, continue disabling generic FCFF DCF and use justified price-to-book, residual-income, or dividend-discount approaches only after regulatory-quality data becomes available.

7. Model 5.0 improvements in priority order
P0: Required before calling the model validated
Build point-in-time statement history with publication timestamps.
Store original and restated values separately.
Reconstruct historical universes, including delistings.
Run walk-forward 1/3/6/12-month return tests.
Include costs, turnover, slippage, and liquidity capacity.
Freeze Model 5.0 parameters before the final untouched test.
Compare against:
Nifty 500
Equal-weight universe
Model 4.x
Quality-only
Momentum-only
Value-only
Simple quality-momentum benchmark
P1: Fix valuation interpretation
Rename current fixed-assumption output to Scenario_DCF.
Add a true Reverse_DCF_Implied_Growth.
Use sector/risk-bucket discount-rate ranges.
Normalize FCFF across several years.
Add bear/base/bull sensitivity matrices.
Add Valuation_Conflict and Valuation_Confidence.
Prevent severe valuation conflicts from receiving an unexplained STRONG BUY.
P2: Improve factor construction
Neutralize factor percentiles within sector or industry.
Neutralize or explicitly control size exposure.
Winsorize inputs before ranking.
Use volatility-adjusted momentum.
Add earnings stability and accrual quality.
Measure factor correlation to avoid double-counting.
Assess whether growth and momentum are unintentionally representing the same information.
Test 35/20/15/25/5 against equal factor weights.
P3: Improve recommendation calibration

Instead of selecting thresholds such as 60 and 70 because they are intuitive, calibrate labels from historical outcomes:

STRONG BUY:
historical top bucket with statistically significant
benchmark-relative forward returns

BUY:
positive expected excess return after estimated costs

HOLD:
insufficient evidence or expected return near benchmark


Until then, call them Tier A, Tier B, and Tier C, or clearly retain the “research heuristic” disclaimer.

Final verdict

Model 5.0 is more reliable as an auditable stock-research prioritization engine than as a recommendation engine. Its architecture is substantially better than a typical retail screener because it separates evidence, policy gates, ranking, liquidity, transcript freshness, data coverage, and operational validation.

But its largest risks are:

No completed point-in-time predictive validation
Potential survivorship and reporting-lag bias
Fixed or insufficiently risk-sensitive DCF assumptions
Unnormalized cash flow
Factor weights that may overreward quality and momentum despite extreme valuation
Mechanically named BUY/STRONG BUY labels without probability calibration

Regarding your negative DCF upside question: a strong factor stock can legitimately be overvalued, but severe negative DCF upside should be surfaced as a valuation conflict rather than buried beneath the combined score. Also, if growth is fixed and the system calculates fair-value upside, that component should be renamed from reverse DCF to scenario DCF. Add a separate true reverse DCF that solves for market-implied growth.

My practical assessment is:

Good enough for research shortlisting and daily monitoring. Not yet sufficiently validated for automated investment decisions or real-money ranking solely from the final rating.