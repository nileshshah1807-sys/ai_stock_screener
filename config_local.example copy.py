# Copy this file to config_local.py and fill in your local-only settings.
# Do not commit or share config_local.py if it contains real credentials.

EMAIL_ENABLED = True
EMAIL_SENDER = "nilesh.shah1807@gmail.com"
EMAIL_RECEIVER = "nilesh.shah1807@gmail.com"
EMAIL_PASSWORD = "YOUR_GMAIL_APP_PASSWORD"
ATTACH_CSV = True

# Faster live test mode. Set SCAN_ALL_NSE = True for a full market scan.
SCAN_ALL_NSE = False
CUSTOM_WATCHLIST = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]

# Reverse DCF defaults. Tune these to your required return and growth view.
REVERSE_DCF_ENABLED = True
REVERSE_DCF_FORECAST_YEARS = 5
REVERSE_DCF_DISCOUNT_RATE = 0.11
REVERSE_DCF_TERMINAL_GROWTH = 0.04
REVERSE_DCF_BASE_GROWTH = 0.15
