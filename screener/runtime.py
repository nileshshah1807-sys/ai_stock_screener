"""Runtime configuration and shared infrastructure."""

import importlib.util
import logging
import os
import smtplib
import socket
from pathlib import Path

import yfinance as yf

logger = logging.getLogger(__name__)

def _env_bool(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name, default):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning(f"Invalid integer for {name}: {value!r}; using {default!r}")
        return default


def _env_float(name, default):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning(f"Invalid float for {name}: {value!r}; using {default!r}")
        return default


def _env_list(name, default):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return [item.strip().upper() for item in value.split(",") if item.strip()]


class IPv4SMTP(smtplib.SMTP):
    def _get_socket(self, host, port, timeout):
        addr = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][4]
        return socket.create_connection(addr, timeout, self.source_address)


class IPv4SMTP_SSL(smtplib.SMTP_SSL):
    def _get_socket(self, host, port, timeout):
        if self.debuglevel > 0:
            self._print_debug("connect:", (host, port))
        addr = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][4]
        new_socket = socket.create_connection(addr, timeout, self.source_address)
        return self.context.wrap_socket(new_socket, server_hostname=host)

# =====================================================
# CONFIGURATION
# =====================================================
class Config:
    # --- Email (disabled by default; enable via config_local.py) ---
    EMAIL_ENABLED = _env_bool("EMAIL_ENABLED", False)
    EMAIL_DELIVERY_METHOD = os.getenv("EMAIL_DELIVERY_METHOD", "SMTP").strip().upper()  # SMTP | BREVO | GMAIL_API
    SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = _env_int("SMTP_PORT", 465)   # 465=SSL (preferred on Railway), 587=STARTTLS
    SMTP_TIMEOUT_SECONDS = _env_int("SMTP_TIMEOUT_SECONDS", 30)
    SMTP_FORCE_IPV4 = _env_bool("SMTP_FORCE_IPV4", True)
    BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
    BREVO_API_URL = os.getenv("BREVO_API_URL", "https://api.brevo.com/v3/smtp/email")
    GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID", "")
    GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "")
    GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN", "")
    GMAIL_TOKEN_URL = os.getenv("GMAIL_TOKEN_URL", "https://oauth2.googleapis.com/token")
    GMAIL_SEND_URL = os.getenv("GMAIL_SEND_URL", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send")
    EMAIL_SENDER = os.getenv("EMAIL_SENDER", "nilesh.shah1807@gmail.com")
    EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")  # Gmail APP password
    # Comma-separated list of recipients, e.g. "a@x.com,b@y.com,c@z.com" - acts as a
    # "group": every address in the list gets the same report (all methods below
    # split/parse this consistently). No group-name/mailing-list feature is needed.
    EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "nilesh.shah1807@gmail.com")
    ATTACH_CSV = _env_bool("ATTACH_CSV", True)  # attach results CSV to the email
    ATTACH_PDF = _env_bool("ATTACH_PDF", True)  # attach a formatted PDF report to the email
    EMAIL_SUBJECT_PREFIX = "Advanced Stock Analysis"

    # --- WhatsApp (disabled by default) ---
    WHATSAPP_ENABLED = False
    WHATSAPP_METHOD = "TWILIO"  # TWILIO | CALLMEBOT | PYWHATKIT
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_WHATSAPP_NUMBER = "whatsapp:+14155238886"
    WHATSAPP_RECEIVER = "+91XXXXXXXXXX"
    CALLMEBOT_API_KEY = os.getenv("CALLMEBOT_API_KEY", "")
    CALLMEBOT_PHONE = "+91XXXXXXXXXX"
    PYWHATKIT_PHONE = "+919898869125"
    PYWHATKIT_WAIT_TIME = 15

    # --- Scanning ---
    SCAN_ALL_NSE = _env_bool("SCAN_ALL_NSE", True)  # Set to True for full NSE scan, False for custom watchlist (faster for testing)
    CUSTOM_WATCHLIST = _env_list("CUSTOM_WATCHLIST", [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
        "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    ])
    TOP_STOCKS_COUNT = _env_int("TOP_STOCKS_COUNT", 20)
    WHATSAPP_TOP_COUNT = _env_int("WHATSAPP_TOP_COUNT", 10)
    NEWS_SENTIMENT_TOP_N = _env_int("NEWS_SENTIMENT_TOP_N", 20)     # fetch news sentiment for top N picks only
    PRICE_CACHE_MAX_AGE_HOURS = _env_int("PRICE_CACHE_MAX_AGE_HOURS", 18)
    FUND_CACHE_MAX_AGE_DAYS = _env_int("FUND_CACHE_MAX_AGE_DAYS", 30)   # fundamentals change slowly; keep cached data longer on Railway

    # --- P3: liquidity pre-filter (applied before the slow fundamentals stage) ---
    LIQUIDITY_FILTER_ENABLED = _env_bool("LIQUIDITY_FILTER_ENABLED", True)
    MIN_PRICE_INR = _env_float("MIN_PRICE_INR", 0.0)          # drop penny stocks
    # Rupee-value average daily turnover (Avg_Volume * Current_Price), not just a raw
    # share count - a 50-lakh turnover bar is a much more meaningful liquidity floor
    # across price points than a fixed share count.
    MIN_AVG_TURNOVER_INR = _env_float("MIN_AVG_TURNOVER_INR", 50_00_000.0)  # Rs 50 lakh/day

    # --- P2: data-completeness gate ---
    REQUIRE_FUND_DATA_FOR_BUY = _env_bool("REQUIRE_FUND_DATA_FOR_BUY", True)
    MIN_FUND_KEY_FIELDS = _env_int("MIN_FUND_KEY_FIELDS", 3)       # of: PE_Ratio, ROE, Profit_Margin, Revenue_Growth

    # Sectors listed here must use a dedicated fundamental branch rather than
    # generic industrial-company ratios before they can receive a BUY rating.
    SPECIALIZED_FUNDAMENTAL_SECTORS = _env_list(
        "SPECIALIZED_FUNDAMENTAL_SECTORS",
        ["Financial Services", "Real Estate"],
    )

    # A STRONG BUY is a high-conviction label, not merely a high blended score.
    # Require independent evidence of both an operating-growth tailwind and a
    # confirmed price trend. These gates do not remove a stock from the ranking;
    # they cap an otherwise-high score at BUY when that evidence is absent.
    STRONG_BUY_MIN_GROWTH = _env_float("STRONG_BUY_MIN_GROWTH", 0.05)
    STRONG_BUY_MIN_TECH_SCORE = _env_float("STRONG_BUY_MIN_TECH_SCORE", 55.0)
    STRONG_BUY_MIN_ADX = _env_float("STRONG_BUY_MIN_ADX", 20.0)

    # --- Sector-relative fundamental scoring ---
    # Blend each fundamental ratio's fixed absolute-threshold score with its
    # percentile rank against same-sector peers in the current scan, so e.g. a PE
    # of 18 is judged against other IT names rather than a single universal bar.
    SECTOR_RELATIVE_FUND_SCORING_ENABLED = _env_bool("SECTOR_RELATIVE_FUND_SCORING_ENABLED", True)
    MIN_SECTOR_PEERS = _env_int("MIN_SECTOR_PEERS", 5)             # need >= this many same-sector peers to trust the percentile
    SECTOR_RELATIVE_FUND_WEIGHT = _env_float("SECTOR_RELATIVE_FUND_WEIGHT", 0.5)  # 0=pure absolute, 1=pure sector-percentile

    # --- Reverse DCF ---
    # Institutional reverse DCF style: infer the cash-flow assumptions already
    # embedded in the current market cap, rather than publishing a single target price.
    REVERSE_DCF_ENABLED = _env_bool("REVERSE_DCF_ENABLED", True)
    REVERSE_DCF_FORECAST_YEARS = _env_int("REVERSE_DCF_FORECAST_YEARS", 5)
    REVERSE_DCF_DISCOUNT_RATE = _env_float("REVERSE_DCF_DISCOUNT_RATE", 0.11)          # WACC / required return
    REVERSE_DCF_TERMINAL_GROWTH = _env_float("REVERSE_DCF_TERMINAL_GROWTH", 0.04)       # fixed terminal growth for implied FCF CAGR
    REVERSE_DCF_BASE_GROWTH = _env_float("REVERSE_DCF_BASE_GROWTH", 0.15)           # explicit growth for implied terminal growth
    REVERSE_DCF_FCF_MARGIN_FALLBACK = _env_float("REVERSE_DCF_FCF_MARGIN_FALLBACK", 0.08)   # used only when FCF is missing but revenue exists
    REVERSE_DCF_MIN_GROWTH = _env_float("REVERSE_DCF_MIN_GROWTH", -0.30)
    REVERSE_DCF_MAX_GROWTH = _env_float("REVERSE_DCF_MAX_GROWTH", 0.60)
    REVERSE_DCF_MIN_TERMINAL_GROWTH = _env_float("REVERSE_DCF_MIN_TERMINAL_GROWTH", -0.05)
    REVERSE_DCF_MAX_TERMINAL_GROWTH = _env_float("REVERSE_DCF_MAX_TERMINAL_GROWTH", 0.09)
    REVERSE_DCF_MIN_VALID_FCF_YIELD = _env_float("REVERSE_DCF_MIN_VALID_FCF_YIELD", 0.005)
    REVERSE_DCF_RANKING_WEIGHT = _env_float("REVERSE_DCF_RANKING_WEIGHT", 0.20)

    # --- Earnings transcript sentiment (primary ranking signal when available) ---
    TRANSCRIPT_SENTIMENT_ENABLED = _env_bool("TRANSCRIPT_SENTIMENT_ENABLED", True)
    TRANSCRIPT_SENTIMENT_WEIGHT = _env_float("TRANSCRIPT_SENTIMENT_WEIGHT", 0.80)
    TRANSCRIPT_MIN_TECHNICAL_SCORE = _env_float("TRANSCRIPT_MIN_TECHNICAL_SCORE", 45.0)
    TRANSCRIPT_FULL_WEIGHT_TECHNICAL_SCORE = _env_float("TRANSCRIPT_FULL_WEIGHT_TECHNICAL_SCORE", 60.0)
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    SUPABASE_TIMEOUT_SECONDS = _env_int("SUPABASE_TIMEOUT_SECONDS", 30)

    # A snapshot score is not a backtest. Measure the realized return after a
    # fixed holding period before making any claim about rating performance.
    BACKTEST_HORIZON_DAYS = _env_int("BACKTEST_HORIZON_DAYS", 30)

    OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "reports_advanced"))
    YFINANCE_CACHE_DIR = Path(os.getenv("YFINANCE_CACHE_DIR", str(OUTPUT_DIR / "yfinance_cache")))

def load_local_config(config_class, config_path):
    if not config_path.exists():
        logger.info('No config_local.py found; using default Config values')
        return
    spec = importlib.util.spec_from_file_location('config_local', config_path)
    config_local = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config_local)
    for key in dir(config_local):
        if not key.startswith('__') and not callable(getattr(config_local, key)) and hasattr(config_class, key):
            setattr(config_class, key, getattr(config_local, key))
    logger.info('Loaded settings from config_local.py')

def configure_runtime_cache(config):
    """Prepare persistent cache folders for price/fundamental data and yfinance metadata."""
    try:
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        config.YFINANCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if hasattr(yf, "set_tz_cache_location"):
            yf.set_tz_cache_location(str(config.YFINANCE_CACHE_DIR))
        logger.info(
            f"Cache directories ready: OUTPUT_DIR={config.OUTPUT_DIR}, "
            f"YFINANCE_CACHE_DIR={config.YFINANCE_CACHE_DIR}"
        )
    except Exception as e:
        logger.warning(f"Cache directory setup failed: {e}")
