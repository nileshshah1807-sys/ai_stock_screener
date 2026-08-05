# AI Stock Screener

Daily NSE stock screener with Reverse DCF analysis, CSV reports, dashboard output, and email delivery.

## Google Cloud Run Jobs

Cloud Run Jobs is a good fit for this application: `app.py` runs one analysis,
sends the email, and exits. The supplied scripts deploy that command as a Job
and create a Cloud Scheduler trigger for 09:00 Asia/Kolkata each day.

Cloud Run's filesystem is ephemeral. Reports and market-data caches are not
preserved between executions, so each job run performs a fresh scan. Email
delivery remains unchanged.

### One-time setup

1. Install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install),
	then authenticate and select the billing-enabled project:

	```powershell
	gcloud auth login
	gcloud config set project YOUR_PROJECT_ID
	```

2. Create the required Secret Manager values. The script prompts for each
	value without printing it:

	```powershell
	.\cloudrun\setup-secrets.ps1 -ProjectId YOUR_PROJECT_ID
	```

	Use `GMAIL_API` for `EMAIL_DELIVERY_METHOD`, and create a new refresh token
	after rotating the credentials exposed earlier.

3. Deploy the Job and the daily scheduler from the repository root:

	```powershell
	.\cloudrun\deploy.ps1 -ProjectId YOUR_PROJECT_ID
	```

4. Run it once and inspect its logs before waiting for the next scheduled run:

	```powershell
	gcloud run jobs execute ai-stock-screener --project=YOUR_PROJECT_ID --region=asia-south1 --wait
	gcloud run jobs executions list --job=ai-stock-screener --project=YOUR_PROJECT_ID --region=asia-south1
	```

The deploy script is idempotent: rerunning it updates the Job and Scheduler.
To use a different time, pass a five-field cron expression and IANA timezone:

```powershell
.\cloudrun\deploy.ps1 -ProjectId YOUR_PROJECT_ID -Schedule "30 8 * * *" -TimeZone "Asia/Kolkata"
```

Cloud Run and Cloud Scheduler require billing to be enabled. Cloud Run has a
monthly free tier; Cloud Scheduler offers three free jobs per billing account.
Check the current pricing pages before relying on those allowances, because
usage beyond them is billable.

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
  
