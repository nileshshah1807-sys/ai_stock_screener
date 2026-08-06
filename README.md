# AI Stock Screener

Daily NSE stock screener with Reverse DCF analysis, CSV reports, dashboard output, and email delivery.

## GitHub Actions

The repository includes a scheduled GitHub Actions workflow that runs `app.py`
once per day. It runs at 03:30 UTC (09:00 Asia/Kolkata). GitHub can delay
scheduled workflows during busy periods. The workflow also supports manual
runs from the **Actions** tab.

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
discovers NSE earnings-call transcripts, keeps PDFs only for the duration of the
job, stores cleaned text and structured results in Supabase, and writes a
sentiment summary in the report tables. A fresh available transcript has the
highest ranking priority and contributes 80% of its `Final_Score`; stocks
without a fresh transcript retain their normal score.

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
repository. Sentiment runs locally with TextBlob sentence polarity supplemented
by a transparent financial positive, negative, uncertainty, and guidance
lexicon; it requires no model API key or paid fallback. This is a reproducible
heuristic signal, not investment advice or a predictive model.

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
FUND_CACHE_MAX_AGE_DAYS=30
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
  
