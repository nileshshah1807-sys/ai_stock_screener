# AI Stock Screener

Daily NSE research screener with auditable fundamental, technical, reverse-DCF,
and management-transcript evidence. Model v4 uses one recommendation finalizer
and separates investment conviction from execution suitability.

The score is a transparent research heuristic, not a validated return forecast.
The evidence, assumptions, known limitations, and validation requirements for
every active model component are recorded in
[`docs/model_methodology.md`](docs/model_methodology.md).

## Project Layout

`app.py` remains the deployment and scheduler entry point. It composes the
workflow and re-exports the long-standing public classes for compatibility.
Application behavior is organized under `screener/`:

```text
screener/
   runtime.py          Configuration, local overrides, and runtime cache setup
   market_data.py      Alternative data, technical indicators, caches, backtests
   data_collection.py  NSE universe, price history, and fundamentals collection
   scoring.py          Generic and sector-specific fundamental/technical scoring
   valuation.py        Evidence-only reverse DCF analysis
   recommendation.py   Single score, gate, rating, and investment-rank policy
   reporting.py        Dashboard, email, PDF, and WhatsApp reporting
   statements.py       Annual-statement collection and factor derivation (Model 5.0)
   benchmark.py        Benchmark index, relative strength, market regime (Model 5.0)
   factors.py          Quality/growth/value/momentum/risk blocks (Model 5.0)
```

Transcript ingestion and local NLP remain in `workers/`, `transcripts/`,
`sentiment/`, and `storage/`. Run the daily screener with `python app.py` or
schedule the same entry point with `python scheduler.py`.

### Model 5.0 (candidate, disabled by default)

The default scoring path is the 4.x model. A candidate **Model 5.0 factor
architecture** is implemented alongside it and selected with
`FACTOR_MODEL_ENABLED=true`. It replaces the 70/30 core score with five
separable factor blocks (quality 35%, growth 20%, value 15%, momentum 25%,
risk 5%), swaps the MA50/ADX trend gates for an MA200 trend gate with
hysteresis and 6/12-month relative strength, adds a market-regime overlay, and
ranks by eligibility class rather than collapsing every capped row onto an
identical 59.99.

It needs data the 4.x path never collected, so enabling it also turns on annual
financial-statement collection (`statement_cache.csv`, 90-day TTL, bounded
per-run backfill) and a benchmark index download. The disabled/default 4.x path
keeps its existing `6mo` download and technical-indicator cache contract v6.
Enabling Model 5.0 selects `2y` and cache contract v7 because a 200-day average
and a 12-1 momentum window cannot be expressed in six months. Features defined
on a six-month window stay pinned to 126 sessions, and v6/v7 caches are kept
distinct so switching the candidate on cannot mix incompatible technical rows.

**Do not enable it in production without validation.** Model 5.0 ratings are
cross-sectional rather than absolute, and it materially re-ranks the universe
(Spearman 0.62 against the 4.x baseline on a 40-name smoke test). Use the
**Candidate model validation (isolated)** workflow with `factor_model: true` to
diff it against a production baseline run, and read section 20 of
`docs/stock_screener_system_architecture.md` first — in particular 20.3 (why the
score is a percentile), 20.8 (financials are barred from BUY by a gate whose
data nobody collects) and 20.9 (the validation protocol and its blocking
point-in-time fundamentals dependency).

## GitHub Actions

The production workflow runs after the configured completed-bar cutoff: 11:00
UTC (16:30 Asia/Kolkata), with a 13:00 UTC (18:30 Asia/Kolkata) recovery trigger
because GitHub cron is best-effort. The collector rejects a same-day bar before
the default 16:15 IST completion cutoff and records `Price_Bar_As_Of`,
`Price_Bar_Complete`, `Price_Fetched_At`, and `Analysis_As_Of`. An after-cutoff
prior-session bar is valid on an exchange holiday; a provisional same-day bar
is not silently reused as an official daily observation.

For a public repository, standard GitHub-hosted runners are free. The runner's
filesystem is temporary, but the workflow restores and saves the reusable
market-data cache between runs. Its original five-path contract is deliberately
pinned to `price_cache.csv`, `fundamental_cache.csv`,
`nse_liquidity_categories.csv`, `backtest_history.csv`, and `yfinance_cache/`.
GitHub includes the declared path list in its hidden cache version, so annual
statements use a separate production statement-cache namespace instead of
invalidating every existing market-data entry. Generated reports remain out of
Git. The first full-NSE run can take around an hour; later runs should reuse data
within the configured cache lifetimes (18 hours for prices and 7 days for
fundamentals). The report is delivered by email as usual. The run also records
model, recommendation-policy, and output-schema versions plus a secret-free
configuration hash and manifest metadata so two runs can be compared exactly.

The separate **Candidate model validation (isolated)** workflow is the safe
path for a branch or model candidate. It runs tests and the screener in a
runner-temporary output/cache directory with email, persistent backtest writes,
and red-flag enrichment disabled. It does receive `SUPABASE_URL` and the service
role secret so it can read the same cached transcript evidence as production,
but `SUPABASE_READ_ONLY=True` rejects every non-GET request. It never sends
notifications, writes backtests, publishes the dashboard, saves a production
cache, or writes Supabase.

When `baseline_run_id` is supplied, the workflow validates and downloads that
report artifact before expensive setup, requires the exact five-path production
cache saved by that run, and refuses a baseline from a different completed price
session instead of silently refetching newer inputs. Annual statements never
enter that production composite cache. They accumulate in a branch-scoped
candidate-only cache, can be explicitly seeded from an earlier validation
artifact with `statement_seed_run_id`, and are checkpointed immediately after a
successful screen even if the later comparison fails. The per-run fetch budget
defaults to 600; `statement_fetch_max_symbols: 2500` is available for a one-time
full-universe completion. A factor-model comparison is rejected below 95%
full-universe statement coverage. Successful comparisons emit top-20 churn,
rank shifts, rating transitions, gate changes, and per-component score deltas;
their artifacts support review but do not promote a candidate.

Run `31674195181` illustrates why these contracts matter. Its cold screen spent
about 59 minutes fetching 2,310 fundamentals and another 15.5 minutes fetching
the first 600 annual-statement records (594 usable); the complete screener step
took about 80 minutes. The later failure was only the baseline-artifact download.
The restored five-path production cache avoids repeating the fundamentals fetch,
while the separate statement cache preserves each bounded backfill tranche.

GitHub Actions cache storage is limited to 10 GB per repository by default,
and cache entries unused for seven days can be removed. Caches must not contain
credentials. Production data caches contain only reusable data files, and the
candidate statement cache lives under runner-temporary storage; Gmail and
Supabase credentials remain GitHub Secrets and are never included in either.

Fundamental scoring selects a model by sector and financial sub-industry.
Banks, NBFCs, insurance companies, and capital-markets firms use separate
equity-quality models; they do not misuse operating debt, current ratio, or
EV/EBITDA as financial-company quality signals. Bank/NBFC book-value points are
paired with ROE, while Gross NPA, Net NPA, and capital adequacy reserve 20-25
points of the score. The current live collector does not yet populate Gross
NPA, Net NPA, capital adequacy, or insurer solvency from a versioned primary
source. It therefore fails closed at `HOLD` for affected bank/NBFC/insurer rows;
weak reported values also fail the specialized quality gate. This is a material
sector-coverage limitation, not evidence that those sectors are unattractive.
`Real Estate` uses an asset-oriented model with book value paired to ROE plus
leverage, liquidity, margins, and growth. Generic reverse DCF remains disabled
for both sectors because the available feed lacks bank regulatory/asset-quality
inputs and property-level NAV/project cash flows.

Sub-1 PE, above-100% profitability, and above-200% point-in-time growth are
flagged as possible one-off/data anomalies rather than receiving maximum
points. One anomaly blocks `STRONG BUY`; multiple anomalies cap the rating at
`HOLD`. CSV, dashboard, email, and PDF output include the selected model,
valuation/quality/growth/income point breakdown, specialized quality reason,
and anomaly reason.

### Model v4 score, coverage, and rank contract

Fundamental, technical, reverse-DCF, and transcript modules produce evidence;
they do not publish the authoritative recommendation. The single finalizer in
`screener/recommendation.py` recomputes the following sequence once, after all
evidence is present:

```text
Core_Score = 0.70 * Fundamental_Score + 0.30 * Technical_Score
Score_After_DCF = Core_Score
                  + w_dcf * (DCF_Valuation_Score - 50) # eligible DCF only
Evidence_Score = Score_After_DCF
                 + w_tx * min(Transcript_Effective_Score - 50, 0)
                                                         # eligible transcript only
Decision_Score = min(Evidence_Score, applicable policy ceiling)
Final_Score = Decision_Score
```

An ineligible evidence stage leaves the preceding score unchanged. DCF uses a
single smooth score, `50 + 50 * tanh(log(base-case value / market cap) / scale)`,
which treats reciprocal favorable/adverse valuation gaps symmetrically around
50. Only a usable result based on reported positive cash flow is blend-eligible
(10% by default); estimated, missing, unsupported-sector, and failed solves are
neutral audit evidence. Reported non-positive cash flow is kept distinct as
unmodelled adverse cash-flow-quality evidence and, by default, caps STRONG BUY
pending a validated normalization model. Transcript evidence is applied after
DCF, at up to 15% by default, and is downside-only in v4. Its applied weight
decays with age and near the reporting-cycle transition. A missing, expired, or
prior-cycle call does not add points, subtract points, cap a rating, or create a
ranking priority.

Technical components report explicit coverage. Their observed score is shrunk
toward neutral when inputs are missing:
`Technical_Score = 50 + Technical_Coverage * (Technical_Observed_Score - 50)`.
Fundamental coverage is the share of fields expected by the selected sector
model. The default BUY minimums are 55% fundamental and 75% technical coverage;
the default STRONG BUY minimums are 75% and 90%. Missing required coverage is
an exported gate failure and caps the final decision below BUY rather than being
treated as neutral evidence.

`Decision_Score` maps mechanically to `STRONG BUY` (70+), `BUY` (60-69.99),
`HOLD` (50-59.99), `REDUCE` (40-49.99), or `SELL` (below 40), after all
coverage, data-quality, specialized-model, anomaly, and trend ceilings. The CSV
keeps four rank views so their purposes are not conflated:

- `Score_Rank`: `Evidence_Score` before decision ceilings.
- `Recommendation_Rank`: published rating class first, then decision/evidence.
- `Investment_Rank`: `Decision_Score` first, then evidence; this is the primary
  `Rank` and the order used by the top-stock report.
- `Actionable_Rank`: executable target orders first, then decision score; this
  liquidity overlay never changes `Decision_Score`, `Rating`, or
  `Investment_Rank`.

### Completed daily-bar snapshot

Price, returns, indicators, volume/turnover, and liquidity statistics use one
completed daily-bar snapshot. Price-dependent valuation ratios are recomputed
onto that close when their raw denominators are available; otherwise their
alignment status identifies fetched metadata rather than claiming false same-
bar precision. Before
the configured `MARKET_BAR_COMPLETE_AFTER_IST` cutoff (16:15 Asia/Kolkata by
default), the collector excludes a same-day Yahoo bar and uses the latest prior
completed session. At or after the cutoff it requires the same-day bar on a
normal session. A symbol lagging the latest expected session is rejected instead
of mixing dates. The
default follows
[NSE's official 16:15 capital-market trade-modification cutoff](https://www.nseindia.com/static/market-data/market-timings);
`ALLOW_PROVISIONAL_MARKET_BARS` remains false by default. The exported
`Price_Bar_As_Of`, `Expected_Price_Bar_As_Of`, `Price_Bar_Session_Lag`,
`Price_Bar_Complete`, `Analysis_As_Of`, `Price_Fetched_At`, and valuation-
alignment fields make the snapshot auditable. Weekday holidays use a versioned,
config-hashed NSE calendar snapshot; the 2026 workflow incorporates
NSE/CMTR/71775 and its NSE/CMTR/72260 modification. Ad-hoc circulars and special
sessions still require an explicit calendar update before the run.

### Liquidity and actionability

The price download calculates traded value as each day's `Close * Volume`.
The CSV includes the 20-day median, 20-day tenth percentile, 60-day median,
the share of 60-day turnover concentrated in the five busiest sessions, and
the percentage of observed sessions on which the stock traded. These measures
avoid treating a one-day volume spike as normal liquidity.

The scan downloads one cached NSE monthly security-category file. Its Group I,
II, and III classification uses six-month trading frequency and mean impact
cost for a Rs1 lakh order. In v4 this evidence does not prefilter the normal
research universe: every collected symbol proceeds to fundamentals and
scoring, and liquidity is applied later as an execution overlay. The legacy
`PREFILTER_RESEARCH_UNIVERSE_BY_LIQUIDITY` escape hatch is false by default and
should be enabled only when runtime constraints require an explicitly filtered
research run.

Investment conviction and execution suitability are separate outputs.
Liquidity never changes `Final_Score` or `Rating`. The report's primary `Rank`
is the score-first `Investment_Rank`; `Actionable_Rank` is the separate view
that puts executable names first. For the configurable
`PORTFOLIO_TARGET_POSITION_INR`
(Rs1 lakh by default), the CSV reports the official NSE impact cost, an
actionable flag, and estimated build days at a conservative 1% participation
in median daily turnover. NSE's impact figure directly supports only its
Rs1 lakh reference order; larger target positions also use the transparent
turnover/concentration proxy. The raw turnover-only estimate is retained as
`Turnover_Proxy_Estimated_Build_Days`; when official impact-cost evidence
directly supports the configured Rs1 lakh order, effective portfolio build
days are reported as one so the two fields are not contradictory.

`CMF_21` and 20-day price return describe whether recent price-volume behaviour
resembles accumulation or distribution. This is labelled a demand proxy, not
institutional-flow proof: OHLCV cannot identify who traded. It is a scored
technical confirmation, not a display-only label. Together with relative
volume it supplies the `VOL`/`Demand_Proxy_Points` component (maximum 15 points)
inside `Technical_Score`: accumulation can confirm high volume, distribution
penalizes it, mixed evidence is neutral, and unavailable evidence contributes
no observed component. It has no separate post-score bonus or rating override.

### Setup

1. Push the workflow to the repository's default branch.
2. In GitHub, open **Settings** > **Secrets and variables** > **Actions** and
   add these repository secrets:

   ```text
   EMAIL_SENDER=your-gmail-address@gmail.com
   EMAIL_RECEIVER=recipient-one@gmail.com,recipient-two@gmail.com
   GMAIL_CLIENT_ID=your_google_oauth_client_id
   GMAIL_CLIENT_SECRET=your_google_oauth_client_secret
   GMAIL_REFRESH_TOKEN=your_google_oauth_refresh_token
   ```

3. Open the **Actions** tab, choose **Daily stock screener**, then select
   **Run workflow** to verify the first email and inspect the logs.

Scheduled workflows in a public repository are disabled after 60 days without
repository activity. Re-enable the workflow in the Actions tab if that occurs.

## Earnings Transcript Sentiment

Transcript collection runs independently at 10:00, 17:00, and 21:00 IST. It
uses a rolling 120-day, idempotent NSE backfill so a newly deployed database can
recover the current reporting season instead of seeing only the last seven
days. Newest filings are processed first, with up to 120 documents collected
and 300 transcripts analyzed per scheduled run. FinBERT sentences are grouped
across transcript chunks and processed through one cached model invocation,
instead of invoking the model separately for every chunk. Each chunk sends at
most 8 high-signal financial sentences to FinBERT; deterministic guidance,
risk, and lexicon rules still inspect the complete text. The transcript batch
and model input sizes are bounded to control runner memory. It keeps PDFs
only for the duration of the
job, stores cleaned text and structured results in Supabase, and writes a
sentiment summary in the report tables. A fresh, validated current-cycle
transcript may contribute at the configured 15% weight, but v4 clamps its
centered contribution to zero or below. It can therefore reduce conviction but
cannot promote the score or recommendation. Lowered guidance,
high risk, and the normalized transcript score remain separately visible for
audit; they are not stacked as duplicate numerical penalties. Older calls have
continuously lower applied weight, and that weight tapers before a reporting-
cycle transition rather than disappearing in a single calendar-day jump.
Eligibility is tied to the Indian quarterly-results calendar: a call remains
current until the next result deadline plus the transcript-publication window.
It then becomes `Prior-cycle`, stays visible for context, and has no score,
rating, or rank effect.
`Transcript_Evidence_Period`, `Transcript_Expected_Period`,
`Transcript_Age_Days`, and `Transcript_Scoring_Eligible` make that decision
auditable. Transcript availability is not a rank tier or tie-break. Companies
are not required to conduct earnings calls, so no transcript is a neutral
evidence path and does not cap an
otherwise eligible `STRONG BUY`. Set
`REQUIRE_TRANSCRIPT_FOR_STRONG_BUY=true` only to restore that optional stricter
gate.

The scheduled worker requires FinBERT when `TRANSCRIPT_REQUIRE_FINBERT=true`.
Model loading or inference failures then fail the job instead of silently
recording a lexicon-only result under a hybrid analysis version.
Tune `TRANSCRIPT_MAX_ANALYSES_PER_RUN`, `TRANSCRIPT_ANALYSIS_BATCH_SIZE`,
`TRANSCRIPT_FINBERT_BATCH_SIZE`, and
`TRANSCRIPT_FINBERT_MAX_SENTENCES_PER_CHUNK` if runner CPU or memory limits
change. CPU runners default to a model batch size of 1; larger model batches are
intended for GPU runners and must be benchmarked. Each run logs elapsed seconds
and transcripts per second for every analysis batch, plus progress for each
bounded FinBERT inference window.

When management gives no explicit raised/maintained/lowered guidance, the
summary says `No explicit guidance` and adds commentary from the stored demand,
revenue, margin, risk, and management-confidence signals instead of displaying
`Unclear` alone.

### Supabase Setup

1. Create a Supabase project, then run [storage/supabase_schema.sql](storage/supabase_schema.sql)
   in its SQL Editor. Re-run this schema file after pulling updates: it safely
   creates the pending-analysis function used by the transcript worker and the
   daily `red_flag_snapshot_history` audit table.
2. In GitHub **Settings** > **Secrets and variables** > **Actions**, add:

   ```text
   SUPABASE_URL=https://YOUR_PROJECT.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
   ```

3. Run **Earnings transcript sentiment** manually once. Then run **Daily stock
   screener** and inspect the CSV columns beginning with `Transcript_`.

For the free red-flag path, run **Red-flag shadow evidence** in
`populate-cache` mode after applying the schema. It then refreshes daily at
02:45 UTC, before the daily screen. The cache remains shadow-only: it does not
change `Final_Score` or `Rating`. Instead, the CSV includes
`Shadow_Red_Flag_*_If_Confirmed` counterfactuals. Severe issuer evidence shows
a hypothetical score/rating cap; severe trading restrictions show a rating or
liquidity constraint without rewriting the fundamental score. The underlying
exchange or issuer filing must be confirmed before either policy is enabled.
Ready-to-run inspection SQL is in
[`storage/red_flag_audit_queries.sql`](storage/red_flag_audit_queries.sql).

The service-role key is intentionally used only by GitHub Actions and the
server-side daily screener. Never expose it to a browser or commit it to the
repository. Sentiment runs locally with FinBERT sentence scoring when the model
is available, a transparent financial positive/negative/uncertainty/constraint
lexicon, explicit guidance rules, and prepared-remarks versus management-Q&A
comparisons. TextBlob remains a baseline and disagreement diagnostic. Set
`TRANSCRIPT_ENABLE_FINBERT=false` to use the deterministic fallback without
loading the model. This is a research feature, not investment advice or a
predictive model.

Supabase Free currently provides a 500 MB database and pauses a project after a
week without activity. The three scheduled worker runs keep the project active;
export the database periodically because the Free plan does not provide
automatic backups. GitHub Actions installs Tesseract for the OCR fallback. For
local OCR runs, install Tesseract separately and ensure it is on `PATH`.

## Free Red-Flag Evidence (Shadow Mode)

The first red-flag phase uses the free, no-key VIGIL feed, which republishes
structured NSE and SEBI disclosures. It currently covers credit-rating events,
promoter pledges, encumbrance events, and exchange surveillance flags. The
worker downloads these four bulk tables once, validates their advertised row
counts and freshness, and stores one compact snapshot per company in Supabase.
The daily stock scan reads those cached snapshots in batches, so it does not
download or analyse all disclosures while scanning stocks.

This phase is deliberately evidence-only. Shadow policy v2 separates issuer
risk from market/trading restrictions and retains the pledge filing quarter,
the percentage of promoter holding encumbered, and the percentage of total
capital encumbered. It adds CSV columns beginning with
`Red_Flag_`, but cannot change `Final_Score`, rating, eligibility, or ranking.
Missing, stale, or malformed source data is reported as unavailable rather than
interpreted as a clean company. The less reliable or currently stale SAST and
related-party datasets are not used in this phase.

Validate locally before enabling anything:

```powershell
python -m unittest discover -s tests
python -m workers.red_flag_worker --dry-run
```

The dry run makes live read-only requests but performs no Supabase writes. To
deploy the cache:

1. Re-run [storage/supabase_schema.sql](storage/supabase_schema.sql) in the
   Supabase SQL Editor to create `red_flag_snapshots`.
2. Configure `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` locally or as GitHub
   secrets.
3. Run `python -m workers.red_flag_worker` once and inspect its row, severity,
   stale-source, and saved-snapshot counts.
4. The daily workflow now defaults `RED_FLAG_ENRICHMENT_ENABLED` to `True`
   because the reviewed cache is populated and policy v2 is active. To suppress
   the audit columns, create the repository variable with value `False`.
   Enrichment remains shadow-only: it never mutates live score or rating.

Policy v2 uses the following conservative interpretation:

- ESM Stage 1 is trading severity 1; ESM Stage 2 is trading severity 2.
- GSM stages 1/2/3-4 are trading severity 1/2/3 respectively.
- ASM Stage 1 is trading severity 1; later stages are trading severity 2.
- Static promoter encumbrance is issuer severity 2 only when it reaches 50%
  of promoter holding or 20% of total capital. It is never critical by itself.
- Credit default, pledge invocation, insolvency, listing-fee default, and
  BZ/SZ listing non-compliance can be issuer severity 3.
- Severity 2 shows a hypothetical `BUY` ceiling if primary evidence is
  confirmed; severity 3 shows a hypothetical `HOLD` ceiling. Both remain
  counterfactual and leave the live recommendation unchanged.

The v2 fields live inside the existing `snapshot` JSON, so an existing Phase 1
Supabase table needs no migration. After deploying v2, rerun the manual action
with `populate-cache` once to replace v1 snapshots.

The **Red-flag shadow evidence** GitHub Action refreshes at 02:45 UTC before
the daily screener. A manual `dry-run` executes the focused safety tests and
validates the live feed without writing; `populate-cache` performs the same
reviewed cache update on demand. Scheduled and populate runs fail closed if
either Supabase secret is missing.

## Railway Cache

Attach a Railway Volume and mount it at `/data`, then set:

```text
OUTPUT_DIR=/data/reports_advanced
YFINANCE_CACHE_DIR=/data/yfinance_cache
FUND_CACHE_MAX_AGE_DAYS=7
PRICE_CACHE_MAX_AGE_HOURS=18
```

Without a Railway Volume, cache files are lost when the container is rebuilt or redeployed.

## Email on Railway

Use Gmail API for Railway. It sends over HTTPS, so it avoids Railway SMTP
network restrictions and avoids shared-domain deliverability problems from
third-party email APIs.

```text
EMAIL_ENABLED=True
EMAIL_DELIVERY_METHOD=GMAIL_API
EMAIL_SENDER=your-gmail-address@gmail.com
EMAIL_RECEIVER=your-address@gmail.com
GMAIL_CLIENT_ID=your_google_oauth_client_id
GMAIL_CLIENT_SECRET=your_google_oauth_client_secret
GMAIL_REFRESH_TOKEN=your_google_oauth_refresh_token
ATTACH_CSV=True
```

Generate the refresh token locally:

```powershell
python tools/generate_gmail_refresh_token.py
```

Authorize the same Gmail account used by `EMAIL_SENDER`.

### Brevo Alternative

Brevo also sends over HTTPS, but Gmail can rate-limit Brevo's shared sender
domain unless you authenticate your own domain.

```text
EMAIL_ENABLED=True
EMAIL_DELIVERY_METHOD=BREVO
EMAIL_SENDER=your-verified-sender@gmail.com
EMAIL_RECEIVER=your-address@gmail.com
BREVO_API_KEY=your_brevo_api_key
ATTACH_CSV=True
```

## Gmail SMTP on Railway

Use a Gmail app password, not your normal Google password:

```text
EMAIL_ENABLED=True
EMAIL_DELIVERY_METHOD=SMTP
EMAIL_SENDER=your-address@gmail.com
EMAIL_RECEIVER=your-address@gmail.com
EMAIL_PASSWORD=your_gmail_app_password
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=465
SMTP_FORCE_IPV4=True
SMTP_TIMEOUT_SECONDS=30
```

`[Errno 101] Network is unreachable` means the container could not reach Gmail before
authentication, so it is not a password rejection. `SMTP_FORCE_IPV4=True` avoids cloud
containers choosing an unreachable IPv6 SMTP route.
  
