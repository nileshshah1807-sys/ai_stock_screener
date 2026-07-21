# AI Stock Screener

Daily NSE stock screener with Reverse DCF analysis, CSV reports, dashboard output, and email delivery.

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

HTTP email APIs are usually more reliable on Railway than direct SMTP. For Brevo:

```text
EMAIL_ENABLED=True
EMAIL_DELIVERY_METHOD=BREVO
EMAIL_SENDER=your-verified-sender@gmail.com
EMAIL_RECEIVER=your-address@gmail.com
BREVO_API_KEY=your_brevo_api_key
ATTACH_CSV=True
```

Verify `EMAIL_SENDER` inside Brevo before deploying.

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
  
