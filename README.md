# AI Stock Screener

Daily NSE stock screener with Reverse DCF analysis, CSV reports, dashboard output, and email delivery.

## GitHub Actions

The repository includes a scheduled GitHub Actions workflow that runs `app.py`
once per day. It runs at 03:37 UTC (09:07 Asia/Kolkata), offset from the hour
because GitHub can delay scheduled workflows during busy periods. The workflow
also supports manual runs from the **Actions** tab.

For a public repository, standard GitHub-hosted runners are free. The runner's
filesystem is temporary, so reports and market-data caches are regenerated on
each execution. The report is delivered by email as usual.

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
  
