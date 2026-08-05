# AI Stock Screener

Daily NSE stock screener with Reverse DCF analysis, CSV reports, dashboard output, and email delivery.

## Render Cron Job

Deploy this as a Render Cron Job, not as a Render free web service. Free web
services sleep after 15 minutes without traffic, so they cannot reliably run
the in-process scheduler. Render Cron Jobs run `app.py` once and exit, which
matches this application's batch design.

The included `render.yaml` runs daily at 09:00 Asia/Kolkata, expressed as
`30 3 * * *` because Render Cron schedules use UTC. It deploys in Singapore.
Render charges cron jobs by active running time and documents a $1 monthly
minimum; Cron Jobs do not have a free plan and cannot use a persistent disk.
Reports and caches are therefore regenerated during each run.

### Deploy

1. Push this branch to GitHub, then sign in to [Render](https://dashboard.render.com/).
2. Select **New** > **Blueprint**, connect the repository, and choose the
   `main` branch. Render reads `render.yaml` automatically.
3. On the first Blueprint deploy, enter the prompted environment values:

   ```text
   EMAIL_SENDER=your-gmail-address@gmail.com
   EMAIL_RECEIVER=recipient-one@gmail.com,recipient-two@gmail.com
   GMAIL_CLIENT_ID=your_google_oauth_client_id
   GMAIL_CLIENT_SECRET=your_google_oauth_client_secret
   GMAIL_REFRESH_TOKEN=your_google_oauth_refresh_token
   ```

   The non-secret email settings are set in `render.yaml`. Keep real tokens
   and secrets out of Git.

4. Select **Manual Deploy** or **Trigger Run** in the Render Cron Job page to
   test the email and inspect the run logs before waiting for the next schedule.

To change the schedule, update the UTC cron value in `render.yaml`. For
example, 08:30 Asia/Kolkata is `0 3 * * *` UTC.

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
  
