# AI Stock Screener

Daily NSE stock screener with Reverse DCF analysis, CSV reports, dashboard output, and email delivery.

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
   valuation.py        Reverse DCF analysis and ranking enrichment
   reporting.py        Dashboard, email, PDF, and WhatsApp reporting
```

Transcript ingestion and local NLP remain in `workers/`, `transcripts/`,
`sentiment/`, and `storage/`. Run the daily screener with `python app.py` or
schedule the same entry point with `python scheduler.py`.

## GitHub Actions

The repository includes a scheduled GitHub Actions workflow that runs `app.py`
once per day. Its primary trigger is 03:17 UTC (08:47 Asia/Kolkata), with a
05:17 UTC recovery trigger because GitHub cron is best-effort and can be delayed
or dropped. The recovery run exits before setup when that day's primary
scheduled run already succeeded. The workflow also supports manual runs from
the **Actions** tab.

For a public repository, standard GitHub-hosted runners are free. The runner's
filesystem is temporary, but the workflow restores and saves the reusable
market-data cache between runs. This retains price data, fundamentals, yfinance
metadata, and backtest history while keeping generated reports out of Git. The
first full-NSE run can take around an hour; later runs should reuse data within
the configured cache lifetimes (18 hours for prices and 30 days for
fundamentals). The report is delivered by email as usual.

GitHub Actions cache storage is limited to 10 GB per repository by default,
and cache entries unused for seven days can be removed. Caches must not contain
credentials; this workflow only caches `reports_advanced/`, while Gmail values
remain GitHub Secrets.

Fundamental scoring selects a model by sector and financial sub-industry.
Banks, NBFCs, insurance companies, and capital-markets firms use separate
equity-quality models; they do not misuse operating debt, current ratio, or
EV/EBITDA as financial-company quality signals. Bank/NBFC book-value points are
paired with ROE, while Gross NPA, Net NPA, and capital adequacy reserve 20-25
points of the score. Missing regulatory data earns no points and prevents a
`STRONG BUY`; weak reported values also fail the specialized quality gate.
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
sentiment summary in the report tables. A fresh validated transcript contributes
15% of `Final_Score`; stocks without a fresh transcript retain their normal
score. Adverse or high-risk calls can reduce a score but cannot promote it.
A validated transcript also forms a confirmation tier within each rating class,
so the concise Top 20 favors current management evidence without allowing a
HOLD transcript stock to bypass a BUY recommendation.
A transcript receives full priority only when its score is at least 55, risk is
at most 60, guidance was not lowered, its technical score is at least 60, and
its trend is confirmed. Scores from 45 to 59.99 with a confirmed trend receive
half the sentiment weight but cannot promote the core recommendation. Weak or
unconfirmed trends receive no transcript weight. Older calls decay toward a
neutral score of 50 rather than toward zero. Within each recommendation class,
fresh full-priority transcript coverage ranks ahead of stocks without a
validated transcript; recommendation safety gates always rank first. A fresh,
quality-validated transcript is required for `STRONG BUY`; an otherwise-
eligible stock without one remains a `BUY` research candidate.

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
   creates the pending-analysis function used by the transcript worker.
2. In GitHub **Settings** > **Secrets and variables** > **Actions**, add:

   ```text
   SUPABASE_URL=https://YOUR_PROJECT.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
   ```

3. Run **Earnings transcript sentiment** manually once. Then run **Daily stock
   screener** and inspect the CSV columns beginning with `Transcript_`.

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
  
