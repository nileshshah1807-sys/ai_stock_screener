# Copy this file to config_local.py for local-only settings.
# Never commit config_local.py if it contains real credentials.

EMAIL_ENABLED = True
EMAIL_SENDER = "nilesh.shah1807@gmail.com"
EMAIL_RECEIVER = "nilesh.shah1807@gmail.com"
EMAIL_PASSWORD = "YOUR_GMAIL_APP_PASSWORD"
ATTACH_CSV = True

SCAN_ALL_NSE = False
CUSTOM_WATCHLIST = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]

REVERSE_DCF_ENABLED = True
REVERSE_DCF_FORECAST_YEARS = 5
REVERSE_DCF_DISCOUNT_RATE = 0.11
REVERSE_DCF_TERMINAL_GROWTH = 0.04
REVERSE_DCF_BASE_GROWTH = 0.15
