# Copy this file to config_local.py for local-only settings.
# Never commit config_local.py if it contains real credentials.

EMAIL_ENABLED = True
EMAIL_SENDER = "nilesh.shah1807@gmail.com"
EMAIL_RECEIVER = "nilesh.shah1807@gmail.com"
EMAIL_PASSWORD = "YOUR_GMAIL_APP_PASSWORD"
ATTACH_CSV = True
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_TIMEOUT_SECONDS = 30
SMTP_FORCE_IPV4 = True


OUTPUT_DIR = "reports_advanced"
YFINANCE_CACHE_DIR = "reports_advanced/yfinance_cache"
FUND_CACHE_MAX_AGE_DAYS = 30
PRICE_CACHE_MAX_AGE_HOURS = 18

SCAN_ALL_NSE = False
CUSTOM_WATCHLIST = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]

REVERSE_DCF_ENABLED = True
REVERSE_DCF_FORECAST_YEARS = 5
REVERSE_DCF_DISCOUNT_RATE = 0.11
REVERSE_DCF_TERMINAL_GROWTH = 0.04
REVERSE_DCF_BASE_GROWTH = 0.15
