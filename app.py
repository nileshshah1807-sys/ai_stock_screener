#!/usr/bin/env python3
"""
STOCK SCREENER ADVANCED (v2.2)
Features: ADX / StochRSI / ATR, Price Cache, Backtest Engine,
Interactive HTML Dashboard, Alternative Data (News sentiment / FII-DII placeholder)

v2.2 review fixes (see CODE_REVIEW.md):
  P1  Fundamentals cache expires after FUND_CACHE_MAX_AGE_DAYS (per-row Cached_Date)
  P2  Empty-input guard + data-completeness gate (thin-data stocks capped at HOLD)
  P3  Liquidity pre-filter before the slow fundamentals stage (full-NSE speedup)
  P4  News sentiment: title-only parsing with word-boundary matching

Secrets are read from environment variables or config_local.py (see
config_local.example.py). NEVER hard-code real passwords in this file.
"""

import yfinance as yf
import pandas as pd
import numpy as np
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
import requests
import warnings
import os
import sys
from pathlib import Path
import logging
import io
import time
import re
import socket
import base64
import importlib.util
import xml.etree.ElementTree as ET

try:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("stock_screener_advanced.log", encoding="utf-8", errors="replace"),
        logging.StreamHandler(),
    ],
)
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
    MIN_PRICE_INR = _env_float("MIN_PRICE_INR", 20.0)          # drop penny stocks
    MIN_AVG_VOLUME = _env_int("MIN_AVG_VOLUME", 100_000)      # drop thinly-traded names (avg daily shares)

    # --- P2: data-completeness gate ---
    REQUIRE_FUND_DATA_FOR_BUY = _env_bool("REQUIRE_FUND_DATA_FOR_BUY", True)
    MIN_FUND_KEY_FIELDS = _env_int("MIN_FUND_KEY_FIELDS", 3)       # of: PE_Ratio, ROE, Profit_Margin, Revenue_Growth

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

    OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "reports_advanced"))
    YFINANCE_CACHE_DIR = Path(os.getenv("YFINANCE_CACHE_DIR", str(OUTPUT_DIR / "yfinance_cache")))

# Load external config overrides (config_local.py sits next to this file)
config_local_path = Path(__file__).with_name("config_local.py")
if config_local_path.exists():
    spec = importlib.util.spec_from_file_location("config_local", config_local_path)
    config_local = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config_local)
    for k in dir(config_local):
        if not k.startswith("__") and not callable(getattr(config_local, k)):
            if hasattr(Config, k):
                setattr(Config, k, getattr(config_local, k))
    logger.info("Loaded settings from config_local.py")
else:
    logger.info("No config_local.py found; using default Config values")

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

# =====================================================
# ALTERNATIVE DATA
# =====================================================
class AlternativeData:
    """News sentiment (Google News RSS) + FII/DII placeholder.
    P4: sentiment now parses ONLY <title> entries and matches WHOLE WORDS
    with word boundaries, so 'gain' no longer fires on 'again' and 'up'
    no longer fires inside 'group'. Overly generic words (up/down) were
    dropped from the lexicon entirely.
    """
    POS_WORDS = [
        "gain", "gains", "rally", "rallies", "surge", "surges", "jump", "jumps",
        "rise", "rises", "bull", "bullish", "record", "upgrade", "upgrades",
        "profit", "profits", "growth", "beat", "beats", "outperform",
        "breakout", "soars", "climbs",
    ]
    NEG_WORDS = [
        "fall", "falls", "drop", "drops", "decline", "declines", "plunge",
        "plunges", "slump", "slumps", "bear", "bearish", "downgrade",
        "downgrades", "loss", "losses", "miss", "misses", "crash", "tumbles",
        "slides", "warning", "fraud", "selloff", "sell-off",
    ]

    @staticmethod
    def _extract_titles(xml_text):
        """Pull <title> texts out of the RSS feed (headlines only, no boilerplate)."""
        try:
            root = ET.fromstring(xml_text)
            titles = [t.text.strip() for t in root.iter("title") if t.text and t.text.strip()]
            if titles:
                return titles
        except ET.ParseError:
            pass
        # fallback: regex (handles minor XML malformation)
        titles = []
        for m in re.findall(r"<title>(.*?</title>)", xml_text, flags=re.S | re.I):
            t = re.sub(r"<!\[CDATA\[|\]\]>", "", m).strip()
            if t:
                titles.append(t)
        return titles

    @staticmethod
    def _analyze_sentiment(titles):
        """Whole-word keyword count over headlines."""
        text = " \n".join(titles).lower()
        pos_pat = r"\b(?:" + "|".join(AlternativeData.POS_WORDS) + r")\b"
        neg_pat = r"\b(?:" + "|".join(AlternativeData.NEG_WORDS) + r")\b"
        pos_score = len(re.findall(pos_pat, text))
        neg_score = len(re.findall(neg_pat, text))
        sentiment = (
            "positive" if pos_score > neg_score
            else "negative" if neg_score > pos_score
            else "neutral"
        )
        return {
            "sentiment": sentiment,
            "positive_hits": pos_score,
            "negative_hits": neg_score,
            "headlines": len(titles),
        }

    @staticmethod
    def get_news_sentiment(symbol):
        try:
            url = f"https://news.google.com/rss/search?q={symbol}+NSE+stock&hl=en-IN&gl=IN&ceid=IN:en"
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200 and "<title>" in resp.text:
                return AlternativeData._analyze_sentiment(
                    AlternativeData._extract_titles(resp.text)
                )
        except Exception as e:
            logger.debug(f"News fetch failed for {symbol}: {e}")
        return {"sentiment": "unknown", "positive_hits": 0, "negative_hits": 0, "headlines": 0}

    @staticmethod
    def get_fii_dii_snapshot():
        """
        PLACEHOLDER. Public FII/DII flow data requires NSE/BSE official feeds,
        NSDL, or a broker API. Replace this with a real source before relying on it.
        """
        return {"fii_trend": "unavailable", "dii_trend": "unavailable", "source": "placeholder"}

    @staticmethod
    def get_earnings_surprise(symbol, ticker_str):
        # Yahoo Finance does not expose earnings surprise via yfinance; skip gracefully.
        return None

# =====================================================
# TECHNICAL INDICATORS
# =====================================================
class TechnicalEnhancer:
    @staticmethod
    def _rsi(close, window=14):
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(window).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def calculate_adx(high, low, close, window=14):
        """Proper Wilder ADX."""
        try:
            high, low, close = high.astype(float), low.astype(float), close.astype(float)
            plus_dm = high.diff()
            minus_dm = -low.diff()
            plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
            minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
            tr = pd.concat(
                [
                    high - low,
                    (high - close.shift(1)).abs(),
                    (low - close.shift(1)).abs(),
                ],
                axis=1,
            ).max(axis=1)
            atr = tr.ewm(alpha=1 / window, min_periods=window).mean()
            plus_di = 100 * plus_dm.ewm(alpha=1 / window, min_periods=window).mean() / atr
            minus_di = 100 * minus_dm.ewm(alpha=1 / window, min_periods=window).mean() / atr
            dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
            adx = dx.ewm(alpha=1 / window, min_periods=window).mean()
            val = adx.iloc[-1]
            return float(val) if not pd.isna(val) else 25.0
        except Exception:
            return 25.0

    @staticmethod
    def calculate_stoch_rsi(close, window=14, k_window=3, d_window=3):
        try:
            rsi_series = TechnicalEnhancer._rsi(close.astype(float), window)
            rsi_min = rsi_series.rolling(window).min()
            rsi_max = rsi_series.rolling(window).max()
            stoch_k = ((rsi_series - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)) * 100
            val = stoch_k.iloc[-1]
            return float(val) if not pd.isna(val) else 50.0
        except Exception:
            return 50.0

    @staticmethod
    def calculate_atr(high, low, close, window=14):
        try:
            high, low, close = high.astype(float), low.astype(float), close.astype(float)
            tr = pd.concat(
                [
                    high - low,
                    (high - close.shift(1)).abs(),
                    (low - close.shift(1)).abs(),
                ],
                axis=1,
            ).max(axis=1)
            atr = tr.rolling(window).mean()
            val = atr.iloc[-1]
            if pd.isna(val):
                return float(close.iloc[-1] * 0.01)
            return float(val)
        except Exception:
            return float(close.iloc[-1] * 0.01)

# =====================================================
# PRICE CACHE
# =====================================================
class PriceCache:
    @staticmethod
    def save(cache_path, records):
        try:
            pd.DataFrame(records).to_csv(cache_path, index=False)
        except Exception as e:
            logger.warning(f"Price cache save failed: {e}")

    @staticmethod
    def load(cache_path, max_age_hours=18):
        """Return cached DataFrame only if the file is fresh enough."""
        try:
            p = Path(cache_path)
            if not p.exists():
                return pd.DataFrame()
            age_hours = (time.time() - p.stat().st_mtime) / 3600
            if age_hours > max_age_hours:
                logger.info(f"Price cache is {age_hours:.1f}h old (> {max_age_hours}h) - ignoring")
                return pd.DataFrame()
            return pd.read_csv(p)
        except Exception:
            return pd.DataFrame()

# =====================================================
# BACKTEST ENGINE
# =====================================================
class BacktestEngine:
    """Log daily scores; compute simple score stats by rating over time."""
    def __init__(self, output_dir):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.output_dir / "backtest_history.csv"

    def log_run(self, date_str, scored_df):
        try:
            snapshot = scored_df[
                ["Symbol", "Current_Price", "Rating", "Combined_Score",
                 "Fundamental_Score", "Technical_Score"]
            ].copy()
            snapshot["Run_Date"] = date_str
            if self.history_file.exists():
                existing = pd.read_csv(self.history_file)
                # drop any earlier rows from the same run date, then append
                existing = existing[existing["Run_Date"] != date_str]
                combined = pd.concat([existing, snapshot], ignore_index=True)
            else:
                combined = snapshot
            combined.to_csv(self.history_file, index=False)
            logger.info(f"Backtest log saved: {len(combined)} total records")
        except Exception as e:
            logger.warning(f"Backtest logging failed: {e}")

    def analyze_performance(self):
        try:
            if not self.history_file.exists():
                return None
            df = pd.read_csv(self.history_file)
            return df.groupby("Rating")["Combined_Score"].mean().round(2).to_dict()
        except Exception as e:
            logger.warning(f"Backtest analysis failed: {e}")
            return None

# =====================================================
# HELPERS
# =====================================================
def fmt_f(val, decimals=1, dash="-"):
    """Safe number formatting for report tables."""
    try:
        if val is None or pd.isna(val):
            return dash
        return f"{float(val):.{decimals}f}"
    except (ValueError, TypeError):
        return dash

def fmt_pct(val, decimals=1, dash="-"):
    """Format a decimal rate as a percentage."""
    try:
        if val is None or pd.isna(val):
            return dash
        return f"{float(val) * 100:.{decimals}f}%"
    except (ValueError, TypeError):
        return dash

def fmt_cr(val, decimals=0, dash="-"):
    """Format INR values in crores for readable reports."""
    try:
        if val is None or pd.isna(val):
            return dash
        return f"{float(val) / 10_000_000:.{decimals}f} Cr"
    except (ValueError, TypeError):
        return dash

# =====================================================
# REVERSE DCF MODEL
# =====================================================
class ReverseDCFModel:
    """Market-implied DCF assumptions for each stock.

    This follows the public institutional reverse-DCF pattern: compare current
    market cap with discounted future free cash flows and solve for the growth
    assumptions required to justify today's price. It is not a proprietary
    Goldman Sachs model; their internal templates are not public.

    The explicit 5-year growth assumption is sector- and size-aware rather than
    a single flat number: mature/defensive sectors (utilities, FMCG) and mega/
    large-cap names get a lower benchmark growth rate, while higher-growth
    sectors (tech, healthcare) and small/mid caps get a higher one. This avoids
    unfairly flagging slow-but-stable compounders as "stretched" just because
    they can't match a generic 15% growth bar, and avoids flattering high-growth
    sectors with too low a bar.
    """

    # Long-run explicit-growth benchmarks by yfinance GICS-style sector name.
    # Values are annual FCF growth rates assumed reasonable for a mature player
    # in that sector over a 5-year explicit forecast window.
    SECTOR_GROWTH_BENCHMARKS = {
        "Technology": 0.18,
        "Communication Services": 0.16,
        "Healthcare": 0.16,
        "Consumer Cyclical": 0.15,
        "Industrials": 0.14,
        "Financial Services": 0.13,
        "Basic Materials": 0.12,
        "Real Estate": 0.12,
        "Energy": 0.10,
        "Consumer Defensive": 0.10,
        "Utilities": 0.08,
    }
    DEFAULT_SECTOR_GROWTH = 0.15  # unknown/missing sector - matches prior flat assumption
    EXPECTED_GROWTH_FLOOR = 0.05
    EXPECTED_GROWTH_CAP = 0.25

    def __init__(self, config):
        self.config = config

    def _size_adjustment(self, market_cap):
        """Mega/large caps grow slower at scale; small/mid caps get a premium."""
        if market_cap is None or market_cap <= 0:
            return 0.0
        market_cap_cr = market_cap / 1e7
        if market_cap_cr >= 200_000:      # mega cap (>= ~Rs 2 lakh Cr)
            return -0.03
        if market_cap_cr >= 20_000:       # large cap
            return -0.015
        if market_cap_cr >= 5_000:        # mid cap
            return 0.0
        return 0.02                        # small cap

    def _expected_growth(self, sector, market_cap):
        """Sector- and size-aware benchmark for the explicit 5Y growth assumption."""
        base = self.SECTOR_GROWTH_BENCHMARKS.get(sector, self.DEFAULT_SECTOR_GROWTH)
        adjusted = base + self._size_adjustment(market_cap)
        return round(max(self.EXPECTED_GROWTH_FLOOR, min(adjusted, self.EXPECTED_GROWTH_CAP)), 4)

    @staticmethod
    def _safe_float(val, default=None):
        try:
            if val is None or pd.isna(val):
                return default
            return float(val)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _dcf_value(base_fcf, growth_rate, terminal_growth, discount_rate, years):
        if (
            base_fcf is None or base_fcf <= 0
            or discount_rate <= terminal_growth
            or years <= 0
            or growth_rate <= -1
            or terminal_growth <= -1
        ):
            return None
        value = 0.0
        fcf = base_fcf
        for year in range(1, years + 1):
            fcf *= 1 + growth_rate
            value += fcf / ((1 + discount_rate) ** year)
        terminal_value = fcf * (1 + terminal_growth) / (discount_rate - terminal_growth)
        value += terminal_value / ((1 + discount_rate) ** years)
        return value

    def _solve_rate(self, target_value, value_func, low, high):
        low_value = value_func(low)
        high_value = value_func(high)
        if low_value is None or high_value is None:
            return None
        if target_value <= low_value:
            return low
        if target_value > high_value:
            return None
        for _ in range(80):
            mid = (low + high) / 2
            mid_value = value_func(mid)
            if mid_value is None:
                return None
            if mid_value < target_value:
                low = mid
            else:
                high = mid
        return (low + high) / 2

    @staticmethod
    def _clamp(value, low=0.0, high=100.0):
        return max(low, min(high, value))

    def _valuation_score(self, status, implied_fcf_growth, implied_terminal_growth, fcf_yield, expected_growth=None):
        if status == "low_fcf_yield":
            return 15.0
        if status != "OK":
            return 25.0
        if implied_fcf_growth is None or pd.isna(implied_fcf_growth):
            return 20.0

        # Score by how the implied growth compares to the sector/size benchmark,
        # not an absolute number - e.g. 15% implied growth is "reasonable" for a
        # tech stock (18% benchmark) but "demanding" for a utility (8% benchmark).
        benchmark = expected_growth if expected_growth else self.DEFAULT_SECTOR_GROWTH
        ratio = implied_fcf_growth / benchmark if benchmark else None

        if implied_fcf_growth < 0:
            score = 95.0
        elif ratio is None:
            score = 50.0
        elif ratio <= 0.53:
            score = 88.0
        elif ratio <= 0.80:
            score = 78.0
        elif ratio <= 1.20:
            score = 62.0
        elif ratio <= 1.67:
            score = 45.0
        elif ratio <= 2.33:
            score = 30.0
        else:
            score = 18.0

        if implied_terminal_growth is not None and not pd.isna(implied_terminal_growth):
            if implied_terminal_growth <= 0.02:
                score += 8.0
            elif implied_terminal_growth > 0.06:
                score -= 8.0
        else:
            score -= 5.0

        if fcf_yield is not None and not pd.isna(fcf_yield):
            if fcf_yield >= 0.05:
                score += 8.0
            elif fcf_yield >= 0.03:
                score += 4.0
            elif fcf_yield < 0.01:
                score -= 8.0

        return round(self._clamp(score), 2)

    def analyze_row(self, row):
        s = self._safe_float
        market_cap = s(row.get("Market_Cap"))
        revenue = s(row.get("Total_Revenue"))
        fcf = s(row.get("Free_CashFlow"))
        total_debt = s(row.get("Total_Debt"))
        total_cash = s(row.get("Total_Cash"))
        fcf_source = "reported"
        sector = row.get("Sector")
        sector = sector.strip() if isinstance(sector, str) and sector.strip() else None
        expected_growth = self._expected_growth(sector, market_cap)

        if (fcf is None or fcf <= 0) and revenue and revenue > 0:
            fcf = revenue * self.config.REVERSE_DCF_FCF_MARGIN_FALLBACK
            fcf_source = "revenue_margin_fallback"

        if market_cap is None or market_cap <= 0:
            return self._empty_result("missing_market_cap", fcf, fcf_source, market_cap, revenue, sector, expected_growth)
        if fcf is None or fcf <= 0:
            return self._empty_result("missing_or_negative_fcf", fcf, fcf_source, market_cap, revenue, sector, expected_growth)

        # Free_CashFlow is unlevered (FCFF), which discounts to Enterprise Value, not
        # equity value directly. Compare/solve against EV = Market Cap + Net Debt rather
        # than Market Cap alone so leveraged companies aren't mis-scored. Falls back to
        # Market Cap (net debt = 0) when debt/cash data is unavailable or degenerate.
        if total_debt is not None and total_debt >= 0 and total_cash is not None and total_cash >= 0:
            net_debt = total_debt - total_cash
            ev_method = "enterprise_value"
        else:
            net_debt = 0.0
            ev_method = "market_cap_fallback"
        enterprise_value = market_cap + net_debt
        if enterprise_value <= 0:
            # Net cash exceeds market cap - an EV-based target would be degenerate.
            enterprise_value = market_cap
            net_debt = 0.0
            ev_method = "market_cap_fallback"

        fcf_yield = fcf / enterprise_value if enterprise_value > 0 else None
        revenue_fcf_margin = fcf / revenue if revenue and revenue > 0 else None
        min_valid_fcf_yield = float(getattr(self.config, "REVERSE_DCF_MIN_VALID_FCF_YIELD", 0.005))
        if fcf_yield is not None and fcf_yield < min_valid_fcf_yield:
            return self._unreliable_result(
                "low_fcf_yield",
                fcf,
                fcf_source,
                market_cap,
                revenue,
                fcf_yield,
                revenue_fcf_margin,
                sector,
                expected_growth,
                net_debt,
                enterprise_value,
                ev_method,
            )

        years = int(self.config.REVERSE_DCF_FORECAST_YEARS)
        discount_rate = float(self.config.REVERSE_DCF_DISCOUNT_RATE)
        fixed_terminal_growth = float(self.config.REVERSE_DCF_TERMINAL_GROWTH)
        fixed_growth = expected_growth
        max_terminal_growth = min(
            float(self.config.REVERSE_DCF_MAX_TERMINAL_GROWTH),
            discount_rate - 0.001,
        )

        implied_fcf_growth = self._solve_rate(
            enterprise_value,
            lambda growth: self._dcf_value(fcf, growth, fixed_terminal_growth, discount_rate, years),
            float(self.config.REVERSE_DCF_MIN_GROWTH),
            float(self.config.REVERSE_DCF_MAX_GROWTH),
        )
        implied_terminal_growth = self._solve_rate(
            enterprise_value,
            lambda terminal: self._dcf_value(fcf, fixed_growth, terminal, discount_rate, years),
            float(self.config.REVERSE_DCF_MIN_TERMINAL_GROWTH),
            max_terminal_growth,
        )

        base_case_ev = self._dcf_value(fcf, fixed_growth, fixed_terminal_growth, discount_rate, years)
        base_case_value = (base_case_ev - net_debt) if base_case_ev is not None else None
        value_to_market = (base_case_value / market_cap) if base_case_value is not None and market_cap > 0 else None
        valuation_gap = (value_to_market - 1) if value_to_market is not None else None
        status = "OK" if implied_fcf_growth is not None else "growth_above_model_range"
        valuation_score = self._valuation_score(status, implied_fcf_growth, implied_terminal_growth, fcf_yield, expected_growth)

        return {
            "DCF_Status": status,
            "DCF_FCF_Source": fcf_source,
            "DCF_Sector": sector if sector else "Unknown",
            "DCF_Expected_Growth": expected_growth,
            "DCF_Base_FCF": round(fcf, 2),
            "DCF_Market_Cap": round(market_cap, 2),
            "DCF_Net_Debt": round(net_debt, 2),
            "DCF_Enterprise_Value": round(enterprise_value, 2),
            "DCF_EV_Method": ev_method,
            "DCF_FCF_Yield": round(fcf_yield, 4) if fcf_yield is not None else np.nan,
            "DCF_Revenue_FCF_Margin": round(revenue_fcf_margin, 4) if revenue_fcf_margin is not None else np.nan,
            "DCF_Years": years,
            "DCF_Discount_Rate": discount_rate,
            "DCF_Assumed_Growth": fixed_growth,
            "DCF_Assumed_Terminal_Growth": fixed_terminal_growth,
            "DCF_Implied_FCF_CAGR": round(implied_fcf_growth, 4) if implied_fcf_growth is not None else np.nan,
            "DCF_Implied_Terminal_Growth": round(implied_terminal_growth, 4) if implied_terminal_growth is not None else np.nan,
            "DCF_Base_Case_Value": round(base_case_value, 2) if base_case_value is not None else np.nan,
            "DCF_Value_to_Market_Cap": round(value_to_market, 4) if value_to_market is not None else np.nan,
            "DCF_Base_Case_Gap": round(valuation_gap, 4) if valuation_gap is not None else np.nan,
            "DCF_Base_Case_Upside": round(valuation_gap, 4) if valuation_gap is not None else np.nan,
            "DCF_Valuation_Score": valuation_score,
            "DCF_Assessment": self._assessment(implied_fcf_growth, implied_terminal_growth, expected_growth),
        }

    @staticmethod
    def _empty_result(status, fcf, fcf_source, market_cap, revenue, sector=None, expected_growth=None):
        return {
            "DCF_Status": status,
            "DCF_FCF_Source": fcf_source,
            "DCF_Sector": sector if sector else "Unknown",
            "DCF_Expected_Growth": expected_growth if expected_growth is not None else np.nan,
            "DCF_Base_FCF": fcf if fcf is not None else np.nan,
            "DCF_Market_Cap": market_cap if market_cap is not None else np.nan,
            "DCF_Net_Debt": np.nan,
            "DCF_Enterprise_Value": np.nan,
            "DCF_EV_Method": "n/a",
            "DCF_FCF_Yield": np.nan,
            "DCF_Revenue_FCF_Margin": np.nan if not revenue or not fcf else fcf / revenue,
            "DCF_Years": np.nan,
            "DCF_Discount_Rate": np.nan,
            "DCF_Assumed_Growth": np.nan,
            "DCF_Assumed_Terminal_Growth": np.nan,
            "DCF_Implied_FCF_CAGR": np.nan,
            "DCF_Implied_Terminal_Growth": np.nan,
            "DCF_Base_Case_Value": np.nan,
            "DCF_Value_to_Market_Cap": np.nan,
            "DCF_Base_Case_Gap": np.nan,
            "DCF_Base_Case_Upside": np.nan,
            "DCF_Valuation_Score": 25.0,
            "DCF_Assessment": "Insufficient data",
        }

    def _unreliable_result(self, status, fcf, fcf_source, market_cap, revenue, fcf_yield, revenue_fcf_margin, sector=None, expected_growth=None, net_debt=None, enterprise_value=None, ev_method=None):
        return {
            "DCF_Status": status,
            "DCF_FCF_Source": fcf_source,
            "DCF_Sector": sector if sector else "Unknown",
            "DCF_Expected_Growth": expected_growth if expected_growth is not None else np.nan,
            "DCF_Base_FCF": round(fcf, 2),
            "DCF_Market_Cap": round(market_cap, 2),
            "DCF_Net_Debt": round(net_debt, 2) if net_debt is not None else np.nan,
            "DCF_Enterprise_Value": round(enterprise_value, 2) if enterprise_value is not None else np.nan,
            "DCF_EV_Method": ev_method if ev_method is not None else "n/a",
            "DCF_FCF_Yield": round(fcf_yield, 4) if fcf_yield is not None else np.nan,
            "DCF_Revenue_FCF_Margin": round(revenue_fcf_margin, 4) if revenue_fcf_margin is not None else np.nan,
            "DCF_Years": int(self.config.REVERSE_DCF_FORECAST_YEARS),
            "DCF_Discount_Rate": float(self.config.REVERSE_DCF_DISCOUNT_RATE),
            "DCF_Assumed_Growth": expected_growth if expected_growth is not None else float(self.config.REVERSE_DCF_BASE_GROWTH),
            "DCF_Assumed_Terminal_Growth": float(self.config.REVERSE_DCF_TERMINAL_GROWTH),
            "DCF_Implied_FCF_CAGR": np.nan,
            "DCF_Implied_Terminal_Growth": np.nan,
            "DCF_Base_Case_Value": np.nan,
            "DCF_Value_to_Market_Cap": np.nan,
            "DCF_Base_Case_Gap": np.nan,
            "DCF_Base_Case_Upside": np.nan,
            "DCF_Valuation_Score": self._valuation_score(status, None, None, fcf_yield, expected_growth),
            "DCF_Assessment": "FCF too low",
        }

    @staticmethod
    def _assessment(implied_fcf_growth, implied_terminal_growth, expected_growth=None):
        if implied_fcf_growth is None:
            return "Very stretched"
        if implied_fcf_growth < 0:
            return "Low expectation"
        benchmark = expected_growth if expected_growth else ReverseDCFModel.DEFAULT_SECTOR_GROWTH
        ratio = implied_fcf_growth / benchmark if benchmark else None
        terminal_ok = implied_terminal_growth is not None and implied_terminal_growth <= 0.04
        if ratio is not None and ratio <= 0.80 and terminal_ok:
            return "Reasonable"
        if ratio is not None and ratio <= 1.50:
            return "Demanding"
        return "Stretched"

    @staticmethod
    def _rating_from_score(score):
        if score >= 70:
            return "STRONG BUY"
        if score >= 60:
            return "BUY"
        if score >= 50:
            return "HOLD"
        if score >= 40:
            return "REDUCE"
        return "SELL"

    def enrich(self, df):
        if df is None or df.empty or not getattr(self.config, "REVERSE_DCF_ENABLED", True):
            return df
        results = [self.analyze_row(row) for _, row in df.iterrows()]
        dcf_df = pd.DataFrame(results, index=df.index)
        enriched = pd.concat([df.copy(), dcf_df], axis=1)
        weight = self._clamp(float(getattr(self.config, "REVERSE_DCF_RANKING_WEIGHT", 0.20)), 0.0, 1.0)
        if weight > 0 and "Combined_Score" in enriched:
            enriched["Pre_DCF_Rank"] = enriched.get("Rank")
            enriched["Pre_DCF_Combined_Score"] = enriched["Combined_Score"]
            has_rating = "Rating" in enriched
            if has_rating:
                enriched["Pre_DCF_Rating"] = enriched["Rating"]
            valuation_score = enriched["DCF_Valuation_Score"].fillna(25.0).clip(0, 100)
            enriched["Final_Score"] = (enriched["Combined_Score"] * (1 - weight) + valuation_score * weight).round(2)
            enriched = enriched.sort_values("Final_Score", ascending=False).reset_index(drop=True)
            enriched["Rank"] = range(1, len(enriched) + 1)
            if has_rating:
                # Recompute the Rating label from the DCF-blended Final_Score so the
                # displayed rating matches the actual rank order shown in reports,
                # instead of leaving it frozen at the pre-DCF Combined_Score rating.
                enriched["Rating"] = enriched["Final_Score"].apply(self._rating_from_score)
                if "Rating_Capped" in enriched:
                    enriched.loc[enriched["Rating_Capped"] == True, "Rating"] = "HOLD"
        ok_count = int((enriched["DCF_Status"] == "OK").sum())
        logger.info(f"Reverse DCF: {ok_count}/{len(enriched)} stocks modeled")
        return enriched

# =====================================================
# INTERACTIVE DASHBOARD
# =====================================================
class InteractiveDashboard:
    @staticmethod
    def generate(scored_df, date_str, output_dir):
        output_path = Path(output_dir) / f"dashboard_{date_str.replace('-', '')}.html"
        try:
            top10 = scored_df.head(10)
            rows_html = ""
            dcf_rows_html = ""
            for _, r in top10.iterrows():
                tag_class = "tag-" + str(r["Rating"]).lower().replace(" ", "-")
                sentiment = r.get("News_Sentiment", "-")
                rows_html += (
                    f"<tr><td>{int(r['Rank'])}</td><td><b>{r['Symbol']}</b></td>"
                    f"<td>₹{r['Current_Price']:,.0f}</td>"
                    f"<td>{fmt_f(r.get('PE_Ratio'), 1)}</td>"
                    f"<td>{r['Fundamental_Score']:.0f}</td>"
                    f"<td>{r['Technical_Score']:.0f}</td>"
                    f"<td><b>{r['Combined_Score']:.1f}</b></td>"
                    f"<td>{sentiment}</td>"
                    f"<td><span class='tag {tag_class}'>{r['Rating']}</span></td></tr>"
                )
                dcf_rows_html += (
                    f"<tr><td>{int(r['Rank'])}</td><td><b>{r['Symbol']}</b></td>"
                    f"<td>{r.get('DCF_Sector', 'Unknown')}</td>"
                    f"<td>\u20b9{r['Current_Price']:,.0f}</td>"
                    f"<td>{fmt_cr(r.get('DCF_Market_Cap'), 0)}</td>"
                    f"<td>{fmt_pct(r.get('DCF_FCF_Yield'), 1)}</td>"
                    f"<td>{fmt_pct(r.get('DCF_Expected_Growth'), 1)}</td>"
                    f"<td>{fmt_pct(r.get('DCF_Implied_FCF_CAGR'), 1)}</td>"
                    f"<td>{fmt_pct(r.get('DCF_Implied_Terminal_Growth'), 1)}</td>"
                    f"<td>{fmt_pct(r.get('DCF_Base_Case_Upside'), 1)}</td>"
                    f"<td>{r.get('DCF_Assessment', '-')}</td>"
                    f"<td><span class='tag {tag_class}'>{r['Rating']}</span></td></tr>"
                )

            # Score distribution histogram (5-point buckets, fixed-width SVG)
            bins = list(range(0, 101, 5))
            counts = (
                pd.cut(scored_df["Combined_Score"].clip(0, 100), bins=bins, include_lowest=True)
                .value_counts()
                .sort_index()
            )
            max_count = int(counts.max()) if len(counts) and counts.max() > 0 else 1
            bar_w, gap = 60, 14
            bars = ""
            for i, (interval, count) in enumerate(counts.items()):
                h = (int(count) / max_count) * 200
                x = 20 + i * (bar_w + gap)
                bars += (
                    f'<rect x="{x}" y="{220 - h:.0f}" width="{bar_w}" height="{h:.0f}" fill="#303f9f" rx="4"/>'
                    f'<text x="{x + bar_w / 2}" y="{214 - h:.0f}" text-anchor="middle" font-size="12" fill="#333">{int(count)}</text>'
                    f'<text x="{x + bar_w / 2}" y="238" text-anchor="middle" font-size="10" fill="#777">{int(interval.left)}-{int(interval.right)}</text>'
                )
            chart_w = 40 + len(counts) * (bar_w + gap)
            html_content = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Stock Screener Dashboard - {date_str}</title>
<style>
body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 20px; background: #f5f7fa; color: #222; }}
.header {{ background: linear-gradient(90deg, #1a237e, #303f9f); color: white; padding: 30px; border-radius: 12px; margin-bottom: 25px; }}
h1 {{ margin: 0; font-size: 28px; letter-spacing: 0.5px; }}
.subtitle {{ opacity: 0.9; margin-top: 8px; font-size: 16px; }}
.card {{ background: white; border-radius: 12px; padding: 22px; margin-bottom: 25px; box-shadow: 0 4px 18px rgba(0,0,0,0.06); }}
h2 {{ color: #1a237e; margin-top: 0; font-size: 22px; border-bottom: 3px solid #e8eaf6; padding-bottom: 10px; }}
.stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 15px; margin-top: 15px; }}
.stat-box {{ background: linear-gradient(135deg, #e8eaf6, #f5f5f5); border-radius: 10px; padding: 18px; text-align: center; }}
.stat-value {{ font-size: 28px; font-weight: bold; color: #1a237e; }}
.stat-label {{ font-size: 12px; color: #555; margin-top: 6px; text-transform: uppercase; letter-spacing: 0.5px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
th {{ background-color: #1a237e; color: white; padding: 12px 8px; text-align: left; font-size: 13px; }}
td {{ padding: 10px 8px; border-bottom: 1px solid #e0e0e0; font-size: 13px; }}
tr:hover {{ background-color: #f8f9ff; }}
.tag {{ display: inline-block; padding: 3px 10px; border-radius: 16px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.3px; }}
.tag-strong-buy {{ background: #e8f5e9; color: #1b5e20; }}
.tag-buy {{ background: #e3f2fd; color: #1565c0; }}
.tag-hold {{ background: #fff3e0; color: #ef6c00; }}
.tag-reduce {{ background: #fbe9e7; color: #d84315; }}
.tag-sell {{ background: #fce4ec; color: #c2185b; }}
.footer {{ text-align: center; color: #777; font-size: 12px; margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; }}
</style>
</head><body>
<div class="header"><h1>📊 Advanced Stock Screener Dashboard</h1>
<div class="subtitle">Analysis Date: {date_str} | Interactive Report v2.2</div></div>
<div class="card"><h2>📈 Market Summary</h2>
<div class="stats">
<div class="stat-box"><div class="stat-value">{len(scored_df)}</div><div class="stat-label">Total Scanned</div></div>
<div class="stat-box"><div class="stat-value">{len(scored_df[scored_df['Rating'] == 'STRONG BUY'])}</div><div class="stat-label">Strong Buy</div></div>
<div class="stat-box"><div class="stat-value">{len(scored_df[scored_df['Rating'] == 'BUY'])}</div><div class="stat-label">Buy</div></div>
<div class="stat-box"><div class="stat-value">{len(scored_df[scored_df['Rating'] == 'HOLD'])}</div><div class="stat-label">Hold</div></div>
<div class="stat-box"><div class="stat-value">{len(scored_df[scored_df['Rating'] == 'SELL'])}</div><div class="stat-label">Sell</div></div>
</div>
</div>
<div class="card"><h2>🏆 Top 10 Picks</h2>
<table><tr><th>Rank</th><th>Symbol</th><th>Price</th><th>PE</th><th>Fund</th><th>Tech</th><th>Score</th><th>News</th><th>Rating</th></tr>
{rows_html}
</table></div>
<div class="card"><h2>🔎 Reverse DCF</h2>
<table><tr><th>Rank</th><th>Symbol</th><th>Sector</th><th>CMP</th><th>Market Cap</th><th>FCF Yield</th><th>Expected Growth</th><th>Implied 5Y FCF CAGR</th><th>Implied Terminal Growth</th><th>Base Case Upside</th><th>Assessment</th><th>Rating</th></tr>
{dcf_rows_html}
</table>
<div style="font-size:12px;color:#777;margin-top:8px;">Reverse DCF solves the market-implied assumptions behind today's market cap using a 5-year DCF model. "Expected Growth" is a sector- and size-aware benchmark (not a single flat rate) used as the explicit growth assumption; "Implied 5Y FCF CAGR" is what the market is actually pricing in.</div>
</div>
<div class="card"><h2>📊 Score Distribution</h2>
<svg viewBox="0 0 {chart_w} 255" style="width:100%;max-height:280px;background:#f8f9ff;border-radius:8px;">
{bars}
</svg>
<div style="font-size:12px;color:#777;margin-top:6px;">Combined score buckets (0–100) vs number of stocks</div>
</div>
<div class="card"><h2>💡 Advanced Features Active</h2>
<ul style="line-height:1.8;font-size:15px;color:#333;">
<li>✅ ADX (Wilder) + Stochastic RSI + ATR technical indicators</li>
<li>✅ Freshness-checked caching (prices 18h / fundamentals 7d)</li>
<li>✅ Liquidity pre-filter (penny &amp; illiquid names excluded)</li>
<li>✅ Data-completeness gate (thin-data stocks capped at HOLD)</li>
<li>✅ Backtest engine (run history tracking + score stats by rating)</li>
<li>✅ Word-boundary news sentiment for top picks (FII/DII feed = placeholder)</li>
<li>✅ Reverse DCF market-implied growth and terminal-growth analysis</li>
<li>✅ Interactive HTML dashboard with embedded SVG charts</li>
</ul>
</div>
<div class="footer">Generated by Stock Screener Advanced v2.2 | Not investment advice. Consult a SEBI-registered advisor.</div>
</body></html>"""

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            logger.info(f"Interactive dashboard generated: {output_path}")
            return str(output_path)
        except Exception as e:
            logger.error(f"Dashboard generation failed: {e}")
            return None

# =====================================================
# STOCK DATA COLLECTOR
# =====================================================
class StockDataCollector:
    # key fundamental fields used by the data-completeness gate (P2)
    FUND_KEY_FIELDS = ("PE_Ratio", "ROE", "Profit_Margin", "Revenue_Growth")

    def __init__(self, config):
        self.config = config

    def get_comprehensive_stock_list(self):
        logger.info("Fetching comprehensive NSE stock list...")
        all_symbols = set()
        try:
            url = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
            resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                df = pd.read_csv(io.StringIO(resp.text))
                all_symbols.update(df["SYMBOL"].dropna().str.strip().tolist())
                logger.info(f"NSE Master: {len(all_symbols)} symbols")
            else:
                logger.error(
                    f"NSE master list returned HTTP {resp.status_code} - "
                    "falling back to built-in watchlist only!"
                )
        except Exception as e:
            logger.error(f"NSE Master fetch failed ({e}) - falling back to built-in watchlist only!")

        # Well-known liquid names as a safety net
        additional_stocks = [
            "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "ITC",
            "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT",
            "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO", "BAJFINANCE", "HCLTECH",
            "WIPRO", "NESTLEIND", "POWERGRID", "NTPC", "M&M", "TATAMOTORS", "ONGC",
            "JSWSTEEL", "TATASTEEL", "ADANIENT", "COALINDIA", "DRREDDY", "CIPLA",
            "DIVISLAB", "TECHM", "GRASIM", "BRITANNIA", "EICHERMOT", "APOLLOHOSP",
            "HEROMOTOCO", "UPL", "BANKBARODA", "LICI", "ZOMATO", "DELHIVERY",
            "HUDCO", "IREDA",
        ]
        all_symbols.update(additional_stocks)
        filtered = {
            str(s).strip().upper()
            for s in all_symbols
            if s and len(str(s)) <= 20 and "-" not in str(s)
        }
        if not self.config.SCAN_ALL_NSE:
            filtered = {s.upper() for s in self.config.CUSTOM_WATCHLIST}
        logger.info(f"Total symbols to scan: {len(filtered)}")
        return sorted(filtered)

    def download_stock_data(self, symbols):
        logger.info(f"Technical download for {len(symbols)} stocks...")
        results = []
        failed = []

        # --- Feature: price cache reuse ---
        cache_path = self.config.OUTPUT_DIR / "price_cache.csv"
        cached = PriceCache.load(cache_path, self.config.PRICE_CACHE_MAX_AGE_HOURS)
        cached_records = []
        to_download = list(symbols)
        if not cached.empty and "Symbol" in cached.columns:
            cached_symbols = set(cached["Symbol"].astype(str))
            cached_records = cached[cached["Symbol"].isin(symbols)].to_dict("records")
            to_download = [s for s in symbols if s not in cached_symbols]
            logger.info(
                f"Price cache hit: {len(cached_records)} reused, {len(to_download)} to download"
            )

        nse_symbols = [s + ".NS" for s in to_download]
        batch_size = 30
        for i in range(0, len(nse_symbols), batch_size):
            batch = nse_symbols[i : i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = max(1, (len(nse_symbols) - 1) // batch_size + 1)
            if batch_num % 5 == 0 or batch_num == 1:
                logger.info(
                    f"Batch {batch_num}/{total_batches} ({len(results) + len(cached_records)} collected)..."
                )
            if batch_num > 1:
                time.sleep(2)
            try:
                data = yf.download(
                    " ".join(batch), period="6mo", group_by="ticker",
                    progress=False, threads=True,
                )
                for symbol in batch:
                    clean_sym = symbol.replace(".NS", "")
                    try:
                        if len(batch) == 1:
                            price_data = data
                        else:
                            if symbol not in data.columns.get_level_values(0):
                                failed.append(clean_sym)
                                continue
                            price_data = data[symbol]
                        if price_data is None or price_data.empty:
                            failed.append(clean_sym)
                            continue
                        closes = price_data["Close"].dropna()
                        volumes = price_data["Volume"].dropna()
                        if len(closes) < 60 or len(volumes) == 0:
                            failed.append(clean_sym)
                            continue
                        current_price = float(closes.iloc[-1])
                        avg_volume = float(volumes.mean())
                        last_volume = float(volumes.iloc[-1])
                        if avg_volume == 0 or pd.isna(avg_volume) or last_volume == 0 or current_price <= 0:
                            failed.append(clean_sym)
                            continue
                        ma20 = float(closes.rolling(20).mean().iloc[-1])
                        ma50 = float(closes.rolling(50).mean().iloc[-1])
                        rsi_series = TechnicalEnhancer._rsi(closes, 14)
                        current_rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else 50.0
                        ema12 = closes.ewm(span=12).mean()
                        ema26 = closes.ewm(span=26).mean()
                        macd = ema12 - ema26
                        signal = macd.ewm(span=9).mean()
                        bb_mid = closes.rolling(20).mean()
                        bb_std = closes.rolling(20).std()
                        bb_upper = bb_mid + 2 * bb_std
                        bb_lower = bb_mid - 2 * bb_std
                        bb_range = float(bb_upper.iloc[-1]) - float(bb_lower.iloc[-1])
                        bb_pos = (
                            (current_price - float(bb_lower.iloc[-1])) / bb_range
                            if bb_range and bb_range > 0 else 0.5
                        )
                        pct_1m = ((current_price / float(closes.iloc[-22])) - 1) * 100 if len(closes) >= 22 else 0.0
                        pct_3m = ((current_price / float(closes.iloc[-66])) - 1) * 100 if len(closes) >= 66 else 0.0
                        pct_6m = ((current_price / float(closes.iloc[0])) - 1) * 100
                        vol_avg_20 = float(volumes.rolling(20).mean().iloc[-1])
                        vol_ratio = last_volume / vol_avg_20 if vol_avg_20 and vol_avg_20 > 0 else 1.0
                        high = price_data["High"].dropna()
                        low = price_data["Low"].dropna()
                        adx_val = TechnicalEnhancer.calculate_adx(high, low, closes, 14)
                        stoch_rsi_val = TechnicalEnhancer.calculate_stoch_rsi(closes, 14)
                        atr_val = TechnicalEnhancer.calculate_atr(high, low, closes, 14)
                        results.append({
                            "Symbol": clean_sym,
                            "Current_Price": round(current_price, 2),
                            "MA20": round(ma20, 2),
                            "MA50": round(ma50, 2),
                            "RSI_14": round(current_rsi, 2),
                            "MACD": round(float(macd.iloc[-1]), 4),
                            "MACD_Signal": round(float(signal.iloc[-1]), 4),
                            "ADX_14": round(adx_val, 2),
                            "StochRSI_14": round(stoch_rsi_val, 2),
                            "ATR_14": round(atr_val, 2),
                            "High_6M": round(float(closes.max()), 2),
                            "Low_6M": round(float(closes.min()), 2),
                            "Pct_Change_1M": round(pct_1m, 2),
                            "Pct_Change_3M": round(pct_3m, 2),
                            "Pct_Change_6M": round(pct_6m, 2),
                            "Avg_Volume": int(avg_volume),
                            "Vol_Ratio": round(vol_ratio, 2),
                            "BB_Position": round(bb_pos, 2),
                        })
                    except Exception:
                        failed.append(clean_sym)
            except Exception as e:
                logger.error(f"Batch {batch_num} error: {e}")
                continue

        all_records = cached_records + results
        if all_records:
            PriceCache.save(cache_path, all_records)
            logger.info(f"Price cache saved ({len(all_records)} records) -> {cache_path}")
        logger.info(
            f"Technical data: {len(all_records)} stocks collected "
            f"({len(results)} fresh, {len(cached_records)} cached, {len(failed)} failed)"
        )
        return pd.DataFrame(all_records)

    # -------------------------------------------------
    # P1: fundamentals cache with per-row TTL
    # -------------------------------------------------
    # Columns that must exist in the cache schema. If a cache file predates one
    # of these (e.g. was written before Sector/Industry were added), every row
    # in it is missing that data forever unless we force a one-time re-fetch.
    REQUIRED_FUND_COLUMNS = ("Sector", "Industry", "Total_Debt", "Total_Cash")

    @staticmethod
    def _split_cache(cached_df, max_age_days):
        """Split cached fundamentals into (fresh_records, stale_symbols) using
        the per-row Cached_Date. Legacy caches without that column, or without
        one of REQUIRED_FUND_COLUMNS (schema upgrade), are treated as fully
        stale (one-off full refresh on first run after upgrade)."""
        if cached_df is None or cached_df.empty or "Symbol" not in cached_df.columns:
            return [], set()
        df = cached_df.copy()
        df["Symbol"] = df["Symbol"].astype(str)
        missing_columns = [c for c in StockDataCollector.REQUIRED_FUND_COLUMNS if c not in df.columns]
        if missing_columns:
            fresh_mask = pd.Series(False, index=df.index)
        elif "Cached_Date" in df.columns:
            dates = pd.to_datetime(df["Cached_Date"], errors="coerce")
            cutoff = pd.Timestamp(datetime.now().date()) - pd.Timedelta(days=max_age_days)
            fresh_mask = dates >= cutoff
        else:
            fresh_mask = pd.Series(False, index=df.index)
        fresh_records = df[fresh_mask].to_dict("records")
        stale_symbols = set(df.loc[~fresh_mask, "Symbol"])
        return fresh_records, stale_symbols

    def get_fundamental_data(self, tech_df):
        cache_file = self.config.OUTPUT_DIR / "fundamental_cache.csv"
        fresh_records, stale_symbols = [], set()
        if cache_file.exists():
            try:
                cached_df = pd.read_csv(cache_file)
                if "Cached_Date" not in cached_df.columns and not cached_df.empty:
                    logger.info(
                        "Legacy fundamentals cache has no Cached_Date column - "
                        "scheduling a one-off full refresh."
                    )
                missing_cols = [c for c in self.REQUIRED_FUND_COLUMNS if c not in cached_df.columns]
                if missing_cols and not cached_df.empty:
                    logger.info(
                        f"Fundamentals cache is missing columns {missing_cols} - "
                        "scheduling a one-off full refresh to backfill them."
                    )
                fresh_records, stale_symbols = self._split_cache(
                    cached_df, self.config.FUND_CACHE_MAX_AGE_DAYS
                )
            except Exception as e:
                logger.warning(f"Fundamental cache load failed: {e}")

        all_symbols = set(tech_df["Symbol"].astype(str))
        fresh_symbols = {r["Symbol"] for r in fresh_records} & all_symbols
        needs_fetch = sorted(all_symbols - fresh_symbols)
        logger.info(
            f"Fundamentals: {len(fresh_symbols)} fresh-cached, "
            f"{len(stale_symbols & all_symbols)} expired (> {self.config.FUND_CACHE_MAX_AGE_DAYS}d), "
            f"{len(needs_fetch)} to fetch"
        )
        fundamental_data = [r for r in fresh_records if r["Symbol"] in all_symbols]
        if not needs_fetch:
            return pd.DataFrame(fundamental_data)

        rate_limit_hits = 0
        last_reset = time.time()
        requests_this_minute = 0
        today_str = datetime.now().strftime("%Y-%m-%d")
        for idx, symbol in enumerate(needs_fetch):
            ticker_str = symbol + ".NS"
            if (idx + 1) % 100 == 0:
                logger.info(f"Fundamentals fetched {idx + 1}/{len(needs_fetch)}")
            requests_this_minute += 1
            if requests_this_minute >= 40:
                elapsed = time.time() - last_reset
                if elapsed < 60:
                    time.sleep(62 - elapsed)
                requests_this_minute = 0
                last_reset = time.time()

            try:
                info = yf.Ticker(ticker_str).info
                if not info or len(info) < 5:
                    continue
                fundamental_data.append({
                    "Symbol": symbol,
                    "Cached_Date": today_str,
                    "PE_Ratio": info.get("trailingPE"),
                    "Forward_PE": info.get("forwardPE"),
                    "PB_Ratio": info.get("priceToBook"),
                    "ROE": info.get("returnOnEquity"),
                    "ROA": info.get("returnOnAssets"),
                    "Debt_to_Equity": info.get("debtToEquity"),
                    "Current_Ratio": info.get("currentRatio"),
                    "Profit_Margin": info.get("profitMargins"),
                    "Operating_Margin": info.get("operatingMargins"),
                    "Gross_Margin": info.get("grossMargins"),
                    "Revenue_Growth": info.get("revenueGrowth"),
                    "Earnings_Growth": info.get("earningsGrowth"),
                    "EPS": info.get("trailingEps"),
                    "Dividend_Yield": info.get("dividendYield"),
                    "Market_Cap": info.get("marketCap"),
                    "EV_EBITDA": info.get("enterpriseToEbitda"),
                    "Free_CashFlow": info.get("freeCashflow"),
                    "Total_Debt": info.get("totalDebt"),
                    "Total_Cash": info.get("totalCash"),
                    "Total_Revenue": info.get("totalRevenue"),
                    "Shares_Outstanding": info.get("sharesOutstanding"),
                    "Book_Value": info.get("bookValue"),
                    "Sector": info.get("sector"),
                    "Industry": info.get("industry"),
                })
            except Exception as e:
                err = str(e).lower()
                if "429" in err or "rate" in err or "too many" in err:
                    rate_limit_hits += 1
                    if rate_limit_hits <= 3:
                        time.sleep(60)
                    elif rate_limit_hits <= 5:
                        time.sleep(120)
                    else:
                        logger.warning("Too many rate-limit hits; stopping fundamental fetch early")
                        break
                continue

        try:
            pd.DataFrame(fundamental_data).to_csv(cache_file, index=False)
            logger.info(f"Fundamental cache saved ({len(fundamental_data)} records)")
        except Exception as e:
            logger.warning(f"Fundamental cache save failed: {e}")
        return pd.DataFrame(fundamental_data)

# =====================================================
# SCORING ENGINE
# =====================================================
FUND_KEY_FIELDS = ("PE_Ratio", "ROE", "Profit_Margin", "Revenue_Growth")

class StockScorer:
    MAX_FUND_SCORE = 100.0
    MAX_TECH_SCORE = 132.0  # sum of max component scores below

    def __init__(self, config=None):
        self.config = config or Config

    @staticmethod
    def safe_float(val, default=None):
        try:
            if val is None or pd.isna(val):
                return default
            return float(val)
        except (ValueError, TypeError):
            return default

    def score_all_stocks(self, merged_df):
        # P2: empty-input guard
        if merged_df is None or len(merged_df) == 0:
            logger.warning("score_all_stocks: empty input - nothing to score")
            return merged_df

        logger.info(f"Scoring {len(merged_df)} stocks...")
        min_key_fields = getattr(self.config, "MIN_FUND_KEY_FIELDS", 3)
        gate_enabled = getattr(self.config, "REQUIRE_FUND_DATA_FOR_BUY", True)

        for idx, row in merged_df.iterrows():
            f_raw = score_fundamentals(row)
            t_raw = self.score_technical(row)

            # normalize both to 0-100
            f_score = round(max(0.0, min(100.0, f_raw / self.MAX_FUND_SCORE * 100)), 2)
            t_score = round(max(0.0, min(100.0, t_raw / self.MAX_TECH_SCORE * 100)), 2)

            # Dynamic weighting: high volatility (ATR% > 3) -> trust technicals a bit more
            price = StockScorer.safe_float(row.get("Current_Price"), 0) or 0
            atr = StockScorer.safe_float(row.get("ATR_14"), price * 0.01) or 0
            atr_pct = (atr / price * 100) if price > 0 else 2.0

            weight_fund, weight_tech = (0.60, 0.40) if atr_pct > 3 else (0.70, 0.30)
            combined = round(f_score * weight_fund + t_score * weight_tech, 2)

            # P2: data-completeness gate - thin-data stocks can't be rated above HOLD
            fields_present = sum(
                1 for k in FUND_KEY_FIELDS if StockScorer.safe_float(row.get(k)) is not None
            )
            data_quality = "FULL" if fields_present >= min_key_fields else "LOW"

            if combined >= 70:
                rating = "STRONG BUY"
            elif combined >= 60:
                rating = "BUY"
            elif combined >= 50:
                rating = "HOLD"
            elif combined >= 40:
                rating = "REDUCE"
            else:
                rating = "SELL"

            rating_capped = bool(gate_enabled and data_quality == "LOW" and combined >= 60)
            if rating_capped:
                rating = "HOLD"

            merged_df.at[idx, "Fundamental_Score"] = f_score
            merged_df.at[idx, "Technical_Score"] = t_score
            merged_df.at[idx, "ATR_Pct"] = round(atr_pct, 2)
            merged_df.at[idx, "Dynamic_Weight_Fund"] = weight_fund
            merged_df.at[idx, "Dynamic_Weight_Tech"] = weight_tech
            merged_df.at[idx, "Combined_Score"] = combined
            merged_df.at[idx, "Fund_Fields_Present"] = fields_present
            merged_df.at[idx, "Data_Quality"] = data_quality
            merged_df.at[idx, "Rating_Capped"] = rating_capped
            merged_df.at[idx, "Rating"] = rating

        merged_df = merged_df.sort_values("Combined_Score", ascending=False).reset_index(drop=True)
        merged_df["Rank"] = range(1, len(merged_df) + 1)

        n_capped = int(merged_df["Rating_Capped"].sum()) if "Rating_Capped" in merged_df else 0
        if n_capped:
            logger.info(f"Data-completeness gate: {n_capped} stock(s) capped at HOLD")
        return merged_df

    @staticmethod
    def score_technical(row):
        s = StockScorer.safe_float
        scores = {}

        rsi = s(row.get("RSI_14"), 50)
        if 40 <= rsi <= 60: scores["RSI"] = 20
        elif 30 <= rsi < 40 or 60 < rsi <= 70: scores["RSI"] = 15
        elif 20 <= rsi < 30 or 70 < rsi <= 80: scores["RSI"] = 8
        elif rsi < 20: scores["RSI"] = 12
        else: scores["RSI"] = 5

        price = s(row.get("Current_Price"), 0) or 0
        ma20 = s(row.get("MA20"), price) or price
        if ma20 > 0 and price > ma20:
            pct = (price / ma20 - 1) * 100
            scores["MA20"] = 12 if pct > 10 else 15 if pct > 5 else 13
        elif ma20 > 0:
            pct = (ma20 / price - 1) * 100 if price > 0 else 99
            scores["MA20"] = 5 if pct > 10 else 7 if pct > 5 else 10
        else:
            scores["MA20"] = 8

        ma50 = s(row.get("MA50"), price) or price
        if ma50 > 0 and price > ma50:
            pct = (price / ma50 - 1) * 100
            scores["MA50"] = 11 if pct > 15 else 15 if pct > 5 else 13
        elif ma50 > 0:
            pct = (ma50 / price - 1) * 100 if price > 0 else 99
            scores["MA50"] = 4 if pct > 15 else 7 if pct > 5 else 10
        else:
            scores["MA50"] = 8

        macd = s(row.get("MACD"), 0) or 0
        signal = s(row.get("MACD_Signal"), 0) or 0
        if macd > signal and macd > 0: scores["MACD"] = 15
        elif macd > signal: scores["MACD"] = 12
        elif macd < signal and macd < 0: scores["MACD"] = 5
        else: scores["MACD"] = 8

        vol_ratio = s(row.get("Vol_Ratio"), 1) or 1
        if vol_ratio > 2: scores["VOL"] = 15
        elif vol_ratio > 1.5: scores["VOL"] = 12
        elif vol_ratio > 1.0: scores["VOL"] = 10
        elif vol_ratio > 0.7: scores["VOL"] = 7
        else: scores["VOL"] = 4

        pct_1m = s(row.get("Pct_Change_1M"), 0) or 0
        if 5 <= pct_1m <= 15: scores["MOM"] = 10
        elif 0 <= pct_1m < 5 or 15 < pct_1m <= 25: scores["MOM"] = 7
        elif -5 <= pct_1m < 0: scores["MOM"] = 5
        elif pct_1m > 25: scores["MOM"] = 4
        else: scores["MOM"] = 3

        bb_pos = s(row.get("BB_Position"), 0.5)
        if bb_pos is None: bb_pos = 0.5
        if 0.3 <= bb_pos <= 0.7: scores["BB"] = 10
        elif 0.1 <= bb_pos < 0.3: scores["BB"] = 8
        elif 0.7 < bb_pos <= 0.9: scores["BB"] = 6
        elif bb_pos < 0.1: scores["BB"] = 7
        else: scores["BB"] = 3

        adx_val = s(row.get("ADX_14"), 25) or 25
        if adx_val > 40: scores["ADX"] = 12
        elif adx_val > 30: scores["ADX"] = 10
        elif adx_val > 20: scores["ADX"] = 7
        else: scores["ADX"] = 3

        stoch_rsi = s(row.get("StochRSI_14"), 50)
        if stoch_rsi is None: stoch_rsi = 50
        if stoch_rsi > 80: scores["STOCH"] = 5
        elif stoch_rsi < 20: scores["STOCH"] = 12
        elif 30 <= stoch_rsi <= 70: scores["STOCH"] = 8
        else: scores["STOCH"] = 6

        atr_val = s(row.get("ATR_14"), price * 0.01)
        atr_pct = (atr_val / price * 100) if price > 0 and atr_val else 5.0
        if atr_pct < 1: scores["ATR"] = 8
        elif atr_pct < 2: scores["ATR"] = 6
        elif atr_pct < 4: scores["ATR"] = 4
        else: scores["ATR"] = 2

        return sum(scores.values())

def score_fundamentals(row):
    """Fundamental quality/valuation score, raw max = 100."""
    s = StockScorer.safe_float
    scores = {}

    pe = s(row.get("PE_Ratio"))
    if pe is None or pe <= 0: scores["PE"] = 6
    elif pe < 15: scores["PE"] = 15
    elif pe < 25: scores["PE"] = 12
    elif pe < 40: scores["PE"] = 8
    else: scores["PE"] = 4

    pb = s(row.get("PB_Ratio"))
    if pb is None or pb <= 0: scores["PB"] = 4
    elif pb < 2: scores["PB"] = 8
    elif pb < 4: scores["PB"] = 6
    elif pb < 8: scores["PB"] = 4
    else: scores["PB"] = 2

    roe = s(row.get("ROE"))
    if roe is None: scores["ROE"] = 6
    elif roe >= 0.25: scores["ROE"] = 15
    elif roe >= 0.15: scores["ROE"] = 12
    elif roe >= 0.10: scores["ROE"] = 8
    elif roe >= 0: scores["ROE"] = 5
    else: scores["ROE"] = 2

    roa = s(row.get("ROA"))
    if roa is None: scores["ROA"] = 3
    elif roa >= 0.10: scores["ROA"] = 5
    elif roa >= 0.05: scores["ROA"] = 4
    elif roa >= 0: scores["ROA"] = 3
    else: scores["ROA"] = 1

    de = s(row.get("Debt_to_Equity"))  # yfinance reports this as a percentage
    if de is None: scores["DE"] = 5
    elif de < 30: scores["DE"] = 10
    elif de < 70: scores["DE"] = 8
    elif de < 150: scores["DE"] = 5
    else: scores["DE"] = 2

    cr = s(row.get("Current_Ratio"))
    if cr is None: scores["CR"] = 4
    elif cr >= 2: scores["CR"] = 7
    elif cr >= 1.2: scores["CR"] = 5
    elif cr >= 1: scores["CR"] = 4
    else: scores["CR"] = 2

    pm = s(row.get("Profit_Margin"))
    if pm is None: scores["PM"] = 5
    elif pm >= 0.20: scores["PM"] = 10
    elif pm >= 0.10: scores["PM"] = 8
    elif pm >= 0.05: scores["PM"] = 6
    elif pm >= 0: scores["PM"] = 4
    else: scores["PM"] = 1

    rg = s(row.get("Revenue_Growth"))
    if rg is None: scores["RG"] = 5
    elif rg >= 0.20: scores["RG"] = 10
    elif rg >= 0.10: scores["RG"] = 8
    elif rg >= 0.05: scores["RG"] = 6
    elif rg >= 0: scores["RG"] = 4
    else: scores["RG"] = 2

    eg = s(row.get("Earnings_Growth"))
    if eg is None: scores["EG"] = 5
    elif eg >= 0.25: scores["EG"] = 10
    elif eg >= 0.15: scores["EG"] = 8
    elif eg >= 0.05: scores["EG"] = 6
    elif eg >= 0: scores["EG"] = 4
    else: scores["EG"] = 2

    dy = s(row.get("Dividend_Yield"))
    if dy is None or dy <= 0: scores["DY"] = 2
    elif dy >= 0.03: scores["DY"] = 5
    elif dy >= 0.015: scores["DY"] = 4
    else: scores["DY"] = 3

    ev = s(row.get("EV_EBITDA"))
    if ev is None or ev <= 0: scores["EV"] = 3
    elif ev < 10: scores["EV"] = 5
    elif ev < 18: scores["EV"] = 4
    elif ev < 30: scores["EV"] = 2
    else: scores["EV"] = 1

    return sum(scores.values())

# =====================================================
# EMAIL REPORTER
# =====================================================
class EmailReporter:
    def __init__(self, config):
        self.config = config

    def create_html_report(self, df, date_str):
        top = df.head(self.config.TOP_STOCKS_COUNT)
        summary = {
            "total": len(df),
            "strong_buy": len(df[df["Rating"] == "STRONG BUY"]),
            "buy": len(df[df["Rating"] == "BUY"]),
            "hold": len(df[df["Rating"] == "HOLD"]),
            "reduce": len(df[df["Rating"] == "REDUCE"]),
            "sell": len(df[df["Rating"] == "SELL"]),
        }
        rows = ""
        dcf_rows = ""
        for _, r in top.iterrows():
            css = "tag-" + str(r["Rating"]).lower().replace(" ", "-")
            wt = f"F {r.get('Dynamic_Weight_Fund', 0.7):.0%} / T {r.get('Dynamic_Weight_Tech', 0.3):.0%}"
            capped_star = "*" if r.get("Rating_Capped") else ""
            rows += (
                f"<tr><td>{int(r['Rank'])}</td><td><b>{r['Symbol']}</b></td>"
                f"<td>₹{r['Current_Price']:,.0f}</td>"
                f"<td>{fmt_f(r.get('PE_Ratio'), 1)}</td>"
                f"<td>{r['Fundamental_Score']:.0f}</td>"
                f"<td>{r['Technical_Score']:.0f}</td>"
                f"<td>{wt}</td>"
                f"<td>{fmt_f(r.get('ADX_14'), 1)}</td>"
                f"<td>{fmt_f(r.get('StochRSI_14'), 1)}</td>"
                f"<td>{fmt_f(r.get('ATR_14'), 2)}</td>"
                f"<td><b>{r['Combined_Score']:.1f}</b></td>"
                f"<td class='{css}'>{r['Rating']}{capped_star}</td></tr>"
            )
            dcf_rows += (
                f"<tr><td>{int(r['Rank'])}</td><td><b>{r['Symbol']}</b></td>"
                f"<td>{r.get('DCF_Sector', 'Unknown')}</td>"
                f"<td>\u20b9{r['Current_Price']:,.0f}</td>"
                f"<td>{fmt_cr(r.get('DCF_Market_Cap'), 0)}</td>"
                f"<td>{fmt_cr(r.get('DCF_Base_FCF'), 0)}</td>"
                f"<td>{fmt_pct(r.get('DCF_FCF_Yield'), 1)}</td>"
                f"<td>{fmt_pct(r.get('DCF_Expected_Growth'), 1)}</td>"
                f"<td>{fmt_pct(r.get('DCF_Implied_FCF_CAGR'), 1)}</td>"
                f"<td>{fmt_pct(r.get('DCF_Implied_Terminal_Growth'), 1)}</td>"
                f"<td>{fmt_pct(r.get('DCF_Base_Case_Upside'), 1)}</td>"
                f"<td>{r.get('DCF_Assessment', '-')}</td>"
                f"<td class='{css}'>{r['Rating']}{capped_star}</td></tr>"
            )

        html = f"""<html><head><style>
body{{font-family:Arial,sans-serif;margin:20px;background:#f5f7fa;}}
.card{{background:white;border-radius:12px;padding:25px;margin-bottom:20px;box-shadow:0 4px 18px rgba(0,0,0,0.06);}}
h1{{color:#1a237e;margin:0;font-size:26px;}}
h2{{color:#303f9f;border-bottom:3px solid #e8eaf6;padding-bottom:10px;margin-top:0;}}
table{{border-collapse:collapse;width:100%;font-size:13px;}}
th{{background:#1a237e;color:white;padding:10px;text-align:center;}}
td{{padding:9px;border-bottom:1px solid #ddd;text-align:center;}}
.tag-strong-buy{{color:#1b5e20;font-weight:bold;}}
.tag-buy{{color:#2e7d32;font-weight:bold;}}
.tag-hold{{color:#f57f17;}}
.tag-reduce{{color:#e65100;}}
.tag-sell{{color:#b71c1c;font-weight:bold;}}
</style></head><body>
<div class="card"><h1>📊 Advanced Stock Screener Report</h1>
<p><b>Date:</b> {date_str} &nbsp;|&nbsp; <b>Features:</b> ADX / StochRSI / ATR, Freshness-checked caches, Liquidity filter, Data-quality gate, Backtest log, News sentiment, Reverse DCF</p></div>
<div class="card"><h2>Market Summary</h2>
<p><b>Total:</b> {summary['total']} |
<span class="tag-strong-buy">Strong Buy: {summary['strong_buy']}</span> |
<span class="tag-buy">Buy: {summary['buy']}</span> |
<span class="tag-hold">Hold: {summary['hold']}</span> |
<span class="tag-reduce">Reduce: {summary['reduce']}</span> |
<span class="tag-sell">Sell: {summary['sell']}</span></p></div>
<div class="card"><h2>Top {self.config.TOP_STOCKS_COUNT} Stocks</h2>
<table><tr><th>Rank</th><th>Symbol</th><th>Price (INR)</th><th>PE</th><th>Fund</th><th>Tech</th><th>Weights</th><th>ADX</th><th>StochRSI</th><th>ATR</th><th>Score</th><th>Rating</th></tr>
{rows}
</table></div>
<div class="card"><h2>Reverse DCF: Market-Implied Expectations</h2>
<p>Model uses a 5-year explicit forecast and a {fmt_pct(self.config.REVERSE_DCF_DISCOUNT_RATE)} discount rate. "Expected Growth" is a sector- and size-aware benchmark (mature/mega-cap sectors get a lower bar, high-growth/small-cap names get a higher one) used as the explicit growth assumption; {fmt_pct(self.config.REVERSE_DCF_TERMINAL_GROWTH)} fixed terminal growth is used when solving for implied FCF CAGR.</p>
<table><tr><th>Rank</th><th>Symbol</th><th>Sector</th><th>CMP</th><th>Market Cap</th><th>Base FCF</th><th>FCF Yield</th><th>Expected Growth</th><th>Implied 5Y FCF CAGR</th><th>Implied Terminal Growth</th><th>Base Case Upside</th><th>Assessment</th><th>Rating</th></tr>
{dcf_rows}
</table></div>
<div class="card"><p><b>Note:</b> Fundamentals &amp; technicals normalized to 0–100, blended with volatility-adaptive weights. Reverse DCF compares market cap to discounted free cash flow and solves for assumptions implied by today's price. * = rating capped at HOLD due to insufficient fundamental data. Not investment advice — consult a SEBI-registered advisor.</p></div>
</body></html>"""
        return html

    def create_pdf_report(self, df, date_str):
        """Render the same Top-N + Reverse DCF data shown in the email as a
        formatted PDF, using reportlab (pure Python, no OS-level dependencies).
        Returns the output path, or None if reportlab isn't installed or the
        PDF could not be built."""
        if not REPORTLAB_AVAILABLE:
            logger.warning("PDF report skipped: reportlab is not installed (add it to requirements.txt).")
            return None
        try:
            top = df.head(self.config.TOP_STOCKS_COUNT)
            pdf_path = self.config.OUTPUT_DIR / f"stock_report_{date_str.replace('-', '')}.pdf"

            styles = getSampleStyleSheet()
            story = [
                Paragraph("Advanced Stock Screener Report", styles["Title"]),
                Paragraph(f"Date: {date_str}", styles["Normal"]),
                Spacer(1, 0.4 * cm),
            ]

            top_header = ["Rank", "Symbol", "CMP", "PE", "Fund", "Tech", "Score", "Rating"]
            top_rows = [top_header]
            for _, r in top.iterrows():
                top_rows.append([
                    int(r["Rank"]),
                    r["Symbol"],
                    f"\u20b9{r['Current_Price']:,.0f}",
                    fmt_f(r.get("PE_Ratio"), 1),
                    f"{r['Fundamental_Score']:.0f}",
                    f"{r['Technical_Score']:.0f}",
                    f"{r['Combined_Score']:.1f}",
                    r["Rating"],
                ])
            story.append(Paragraph(f"Top {self.config.TOP_STOCKS_COUNT} Stocks", styles["Heading2"]))
            story.append(self._pdf_table(top_rows, [1.4, 2.6, 2.0, 1.6, 1.6, 1.6, 1.6, 2.2]))
            story.append(Spacer(1, 0.6 * cm))

            dcf_header = [
                "Rank", "Symbol", "Sector", "CMP", "Mkt Cap", "FCF Yield",
                "Exp Growth", "Impl 5Y CAGR", "Impl Term Growth", "Upside", "Assessment", "Rating",
            ]
            dcf_rows = [dcf_header]
            for _, r in top.iterrows():
                dcf_rows.append([
                    int(r["Rank"]),
                    r["Symbol"],
                    r.get("DCF_Sector", "Unknown"),
                    f"\u20b9{r['Current_Price']:,.0f}",
                    fmt_cr(r.get("DCF_Market_Cap"), 0),
                    fmt_pct(r.get("DCF_FCF_Yield"), 1),
                    fmt_pct(r.get("DCF_Expected_Growth"), 1),
                    fmt_pct(r.get("DCF_Implied_FCF_CAGR"), 1),
                    fmt_pct(r.get("DCF_Implied_Terminal_Growth"), 1),
                    fmt_pct(r.get("DCF_Base_Case_Upside"), 1),
                    r.get("DCF_Assessment", "-"),
                    r["Rating"],
                ])
            story.append(Paragraph("Reverse DCF: Market-Implied Expectations", styles["Heading2"]))
            story.append(self._pdf_table(
                dcf_rows,
                [1.1, 2.0, 2.2, 1.8, 2.0, 1.8, 1.8, 2.0, 2.1, 1.6, 2.2, 1.8],
            ))
            story.append(Spacer(1, 0.4 * cm))
            story.append(Paragraph(
                "Not investment advice - consult a SEBI-registered advisor.",
                styles["Italic"],
            ))

            doc = SimpleDocTemplate(
                str(pdf_path),
                pagesize=landscape(A4),
                topMargin=1.2 * cm, bottomMargin=1.2 * cm, leftMargin=1.2 * cm, rightMargin=1.2 * cm,
            )
            doc.build(story)
            return pdf_path
        except Exception as e:
            logger.warning(f"PDF report generation failed: {e}")
            return None

    @staticmethod
    def _pdf_table(rows, col_widths_cm):
        table = Table(rows, colWidths=[w * cm for w in col_widths_cm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a237e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("FONTSIZE", (0, 0), (-1, 0), 7.5),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7fa")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return table

    def _build_message(self, html_content, date_str, csv_path, pdf_path=None):
        recipients = [addr.strip() for addr in self.config.EMAIL_RECEIVER.split(",") if addr.strip()]
        msg = MIMEMultipart()
        msg["From"] = self.config.EMAIL_SENDER
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = f"{self.config.EMAIL_SUBJECT_PREFIX} - {date_str}"
        msg.attach(MIMEText(html_content, "html"))
        if csv_path and os.path.exists(csv_path) and self.config.ATTACH_CSV:
            with open(csv_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(csv_path)}")
                msg.attach(part)
        if pdf_path and os.path.exists(pdf_path) and self.config.ATTACH_PDF:
            with open(pdf_path, "rb") as f:
                part = MIMEBase("application", "pdf")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(pdf_path)}")
                msg.attach(part)
        return msg

    def _build_brevo_payload(self, html_content, date_str, csv_path, pdf_path=None):
        payload = {
            "sender": {
                "email": self.config.EMAIL_SENDER,
                "name": self.config.EMAIL_SUBJECT_PREFIX,
            },
            "to": [{"email": email.strip()} for email in self.config.EMAIL_RECEIVER.split(",") if email.strip()],
            "subject": f"{self.config.EMAIL_SUBJECT_PREFIX} - {date_str}",
            "htmlContent": html_content,
        }
        attachments = []
        if csv_path and os.path.exists(csv_path) and self.config.ATTACH_CSV:
            with open(csv_path, "rb") as f:
                attachments.append({
                    "name": os.path.basename(csv_path),
                    "content": base64.b64encode(f.read()).decode("ascii"),
                })
        if pdf_path and os.path.exists(pdf_path) and self.config.ATTACH_PDF:
            with open(pdf_path, "rb") as f:
                attachments.append({
                    "name": os.path.basename(pdf_path),
                    "content": base64.b64encode(f.read()).decode("ascii"),
                })
        if attachments:
            payload["attachment"] = attachments
        return payload

    def _send_email_brevo(self, html_content, date_str, csv_path=None, pdf_path=None):
        if not self.config.BREVO_API_KEY:
            logger.error("Brevo email not sent: BREVO_API_KEY is required when EMAIL_DELIVERY_METHOD=BREVO.")
            return False

        payload = self._build_brevo_payload(html_content, date_str, csv_path, pdf_path)
        if not payload["to"]:
            logger.error("Brevo email not sent: EMAIL_RECEIVER must contain at least one email address.")
            return False

        try:
            response = requests.post(
                self.config.BREVO_API_URL,
                headers={
                    "accept": "application/json",
                    "api-key": self.config.BREVO_API_KEY,
                    "content-type": "application/json",
                },
                json=payload,
                timeout=self.config.SMTP_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            logger.error(f"Brevo email network/API request failed: {e}")
            return False

        if 200 <= response.status_code < 300:
            logger.info(f"Email sent to {self.config.EMAIL_RECEIVER} via Brevo HTTP API")
            return True

        logger.error(f"Brevo email failed: HTTP {response.status_code} {response.text[:500]}")
        return False

    def _get_gmail_api_access_token(self):
        missing = [
            name for name in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN")
            if not getattr(self.config, name)
        ]
        if missing:
            logger.error(f"Gmail API email not sent: missing {', '.join(missing)}.")
            return None

        try:
            response = requests.post(
                self.config.GMAIL_TOKEN_URL,
                data={
                    "client_id": self.config.GMAIL_CLIENT_ID,
                    "client_secret": self.config.GMAIL_CLIENT_SECRET,
                    "refresh_token": self.config.GMAIL_REFRESH_TOKEN,
                    "grant_type": "refresh_token",
                },
                timeout=self.config.SMTP_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            logger.error(f"Gmail API token refresh failed: {e}")
            return None

        if 200 <= response.status_code < 300:
            token = response.json().get("access_token")
            if token:
                return token
            logger.error(f"Gmail API token refresh response did not include access_token: {response.text[:500]}")
            return None

        logger.error(f"Gmail API token refresh failed: HTTP {response.status_code} {response.text[:500]}")
        return None

    def _send_email_gmail_api(self, html_content, date_str, csv_path=None, pdf_path=None):
        token = self._get_gmail_api_access_token()
        if not token:
            return False

        msg = self._build_message(html_content, date_str, csv_path, pdf_path)
        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        try:
            response = requests.post(
                self.config.GMAIL_SEND_URL,
                headers={
                    "authorization": f"Bearer {token}",
                    "content-type": "application/json",
                },
                json={"raw": raw_message},
                timeout=self.config.SMTP_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            logger.error(f"Gmail API send request failed: {e}")
            return False

        if 200 <= response.status_code < 300:
            message_id = response.json().get("id", "unknown")
            logger.info(f"Email sent to {self.config.EMAIL_RECEIVER} via Gmail API; message id={message_id}")
            return True

        logger.error(f"Gmail API send failed: HTTP {response.status_code} {response.text[:500]}")
        return False

    def send_email(self, html_content, date_str, csv_path=None, pdf_path=None):
        if not self.config.EMAIL_ENABLED:
            logger.info("Email disabled; set EMAIL_ENABLED=True in config_local.py to send")
            return False
        if not self.config.EMAIL_SENDER or not self.config.EMAIL_RECEIVER:
            logger.error("Email not sent: EMAIL_SENDER and EMAIL_RECEIVER are required.")
            return False
        if self.config.EMAIL_DELIVERY_METHOD == "BREVO":
            return self._send_email_brevo(html_content, date_str, csv_path, pdf_path)
        if self.config.EMAIL_DELIVERY_METHOD == "GMAIL_API":
            return self._send_email_gmail_api(html_content, date_str, csv_path, pdf_path)
        if self.config.EMAIL_DELIVERY_METHOD != "SMTP":
            logger.error(
                f"Unsupported EMAIL_DELIVERY_METHOD={self.config.EMAIL_DELIVERY_METHOD!r}; "
                "use SMTP, BREVO, or GMAIL_API."
            )
            return False
        if not self.config.EMAIL_PASSWORD:
            logger.error(
                "SMTP email not sent: EMAIL_PASSWORD is required. "
                "For Gmail, use an app password via environment variable or config_local.py."
            )
            return False
        msg = self._build_message(html_content, date_str, csv_path, pdf_path)
        # Try port 465 (SSL) first — works on most cloud hosts including Railway.
        # Fall back to port 587 (STARTTLS) if 465 is unreachable.
        configured_port = self.config.SMTP_PORT
        fallback_port = 587 if configured_port == 465 else 465
        attempts = [
            (configured_port, "SSL" if configured_port == 465 else "STARTTLS"),
            (fallback_port, "SSL" if fallback_port == 465 else "STARTTLS"),
        ]
        smtp_ssl_class = IPv4SMTP_SSL if self.config.SMTP_FORCE_IPV4 else smtplib.SMTP_SSL
        smtp_class = IPv4SMTP if self.config.SMTP_FORCE_IPV4 else smtplib.SMTP
        for port, mode in attempts:
            try:
                if mode == "SSL":
                    with smtp_ssl_class(self.config.SMTP_SERVER, port, timeout=self.config.SMTP_TIMEOUT_SECONDS) as server:
                        server.login(self.config.EMAIL_SENDER, self.config.EMAIL_PASSWORD)
                        server.send_message(msg)
                else:
                    with smtp_class(self.config.SMTP_SERVER, port, timeout=self.config.SMTP_TIMEOUT_SECONDS) as server:
                        server.ehlo()
                        server.starttls()
                        server.ehlo()
                        server.login(self.config.EMAIL_SENDER, self.config.EMAIL_PASSWORD)
                        server.send_message(msg)
                logger.info(f"Email sent to {self.config.EMAIL_RECEIVER} via port {port} ({mode})")
                return True
            except smtplib.SMTPAuthenticationError as e:
                logger.error(
                    f"Email authentication failed on port {port} ({mode}). "
                    "Your Gmail app password, sender address, or Google account settings are invalid. "
                    f"SMTP response: {e.smtp_code} {e.smtp_error!r}"
                )
                return False
            except OSError as e:
                logger.warning(
                    f"Email network attempt port {port} ({mode}) failed: {e}. "
                    f"SMTP_FORCE_IPV4={self.config.SMTP_FORCE_IPV4}"
                )
            except Exception as e:
                logger.warning(f"Email attempt port {port} ({mode}) failed: {e}")
        logger.error(
            "Email failed on all SMTP attempts. If the error is network-related, check Railway outbound "
            "connectivity/firewall; if it says authentication failed, regenerate the Gmail app password."
        )
        return False

# =====================================================
# WHATSAPP REPORTER (self-contained: Twilio / CallMeBot / PyWhatKit)
# =====================================================
class WhatsAppReporter:
    def __init__(self, config):
        self.config = config

    def create_whatsapp_message(self, df, date_str):
        top = df.head(self.config.WHATSAPP_TOP_COUNT)
        msg = f"*ADVANCED STOCK REPORT {date_str}*\n"
        msg += (
            f"Total: {len(df)} | STRONG BUY: {len(df[df['Rating'] == 'STRONG BUY'])} "
            f"| BUY: {len(df[df['Rating'] == 'BUY'])}\n"
            f"Features: ADX/Stoch/ATR, Smart caches, Liquidity filter, Dashboard, News\n\n"
        )
        for _, r in top.iterrows():
            msg += (
                f"{int(r['Rank'])}. {r['Symbol']} ₹{r['Current_Price']:,.0f} "
                f"Score:{r['Combined_Score']:.0f} {r['Rating']} ADX:{fmt_f(r.get('ADX_14'), 0)}\n"
            )
        msg += "\nDisclaimer: Not investment advice. Consult a SEBI-registered advisor."
        return msg

    def send_via_twilio(self, message):
        from twilio.rest import Client
        client = Client(self.config.TWILIO_ACCOUNT_SID, self.config.TWILIO_AUTH_TOKEN)
        to = self.config.WHATSAPP_RECEIVER
        if not to.startswith("whatsapp:"):
            to = f"whatsapp:{to}"
        client.messages.create(body=message, from_=self.config.TWILIO_WHATSAPP_NUMBER, to=to)
        logger.info("WhatsApp sent via Twilio")

    def send_via_callmebot(self, message):
        resp = requests.get(
            "https://api.callmebot.com/whatsapp.php",
            params={
                "phone": self.config.CALLMEBOT_PHONE,
                "text": message,
                "apikey": self.config.CALLMEBOT_API_KEY,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            logger.info("WhatsApp sent via CallMeBot")
        else:
            logger.warning(f"CallMeBot returned HTTP {resp.status_code}")

    def send_via_pywhatkit(self, message):
        # NOTE: requires a desktop with a browser logged into WhatsApp Web;
        # will NOT work on a headless server. Prefer TWILIO or CALLMEBOT there.
        import pywhatkit
        now = datetime.now()
        send_min = now.minute + 2
        send_hour = now.hour
        if send_min >= 60:
            send_min -= 60
            send_hour = (send_hour + 1) % 24
        pywhatkit.sendwhatmsg(
            self.config.PYWHATKIT_PHONE, message,
            send_hour, send_min, wait_time=self.config.PYWHATKIT_WAIT_TIME,
        )
        logger.info("WhatsApp scheduled via PyWhatKit")

    def send_whatsapp(self, df, date_str):
        if not self.config.WHATSAPP_ENABLED:
            return
        message = self.create_whatsapp_message(df, date_str)
        method = str(self.config.WHATSAPP_METHOD).upper()
        if method == "TWILIO":
            self.send_via_twilio(message)
        elif method == "CALLMEBOT":
            self.send_via_callmebot(message)
        elif method == "PYWHATKIT":
            self.send_via_pywhatkit(message)
        else:
            logger.warning(f"Unknown WHATSAPP_METHOD: {method}")

# =====================================================
# MAIN
# =====================================================
def run_daily_analysis():
    logger.info("=" * 60)
    logger.info("STARTING ADVANCED STOCK ANALYSIS (v2.2)")
    logger.info("=" * 60)
    config = Config()
    configure_runtime_cache(config)
    date_str = datetime.now().strftime("%d-%m-%Y")
    logger.info(f"Analysis date: {date_str}")

    collector = StockDataCollector(config)
    symbols = collector.get_comprehensive_stock_list()
    tech_df = collector.download_stock_data(symbols)
    if tech_df.empty:
        logger.error("No technical data. Exiting.")
        return

    # P3: liquidity pre-filter before the slow per-ticker fundamentals stage
    if config.LIQUIDITY_FILTER_ENABLED and config.SCAN_ALL_NSE:
        before = len(tech_df)
        tech_df = tech_df[
            (tech_df["Current_Price"] >= config.MIN_PRICE_INR)
            & (tech_df["Avg_Volume"] >= config.MIN_AVG_VOLUME)
        ].reset_index(drop=True)
        logger.info(
            f"Liquidity filter: kept {len(tech_df)}/{before} "
            f"(dropped {before - len(tech_df)} names below Rs{config.MIN_PRICE_INR:.0f} "
            f"or {config.MIN_AVG_VOLUME:,} avg shares)"
        )
        if tech_df.empty:
            logger.error("Liquidity filter removed every stock. Exiting.")
            return

    alt_data = AlternativeData.get_fii_dii_snapshot()
    logger.info(f"Alternative data (FII/DII): {alt_data}")

    fund_df = collector.get_fundamental_data(tech_df)
    if fund_df.empty:
        logger.error("No fundamental data. Exiting.")
        return

    merged_df = pd.merge(tech_df, fund_df, on="Symbol", how="inner")
    logger.info(f"Merged: {len(merged_df)} stocks")
    if merged_df.empty:
        logger.error("Nothing left after merge - check symbol overlap and caches. Exiting.")
        return

    scorer = StockScorer(config)
    scored_df = scorer.score_all_stocks(merged_df)
    if scored_df is None or len(scored_df) == 0:
        logger.error("Scoring produced no rows. Exiting.")
        return

    if config.REVERSE_DCF_ENABLED:
        scored_df = ReverseDCFModel(config).enrich(scored_df)

    # News sentiment for the top N picks (post-scoring, so it's the *actual* top N)
    n = min(config.NEWS_SENTIMENT_TOP_N, len(scored_df))
    sentiment_map = {}
    for sym in scored_df["Symbol"].head(n):
        sentiment_map[sym] = AlternativeData.get_news_sentiment(sym)["sentiment"]
    scored_df["News_Sentiment"] = scored_df["Symbol"].map(
        lambda s: sentiment_map.get(s, "-")
    )
    logger.info(f"News sentiment fetched for top {len(sentiment_map)} symbols")

    csv_path = config.OUTPUT_DIR / f"advanced_analysis_{datetime.now().strftime('%Y%m%d')}.csv"
    scored_df.to_csv(csv_path, index=False)
    logger.info(f"Results saved: {csv_path}")

    # Backtest log
    backtest = BacktestEngine(config.OUTPUT_DIR)
    backtest.log_run(date_str, scored_df)
    perf = backtest.analyze_performance()
    if perf:
        logger.info(f"Avg combined score by rating (all runs): {perf}")

    # Dashboard
    dashboard_path = InteractiveDashboard.generate(scored_df, date_str, config.OUTPUT_DIR)

    # Email (send_email handles its own retries and returns False on failure; no re-raise)
    if config.EMAIL_ENABLED:
        reporter = EmailReporter(config)
        html = reporter.create_html_report(scored_df, date_str)
        pdf_path = reporter.create_pdf_report(scored_df, date_str) if config.ATTACH_PDF else None
        reporter.send_email(
            html,
            date_str,
            csv_path if config.ATTACH_CSV else None,
            pdf_path if config.ATTACH_PDF else None,
        )

    # WhatsApp
    if config.WHATSAPP_ENABLED:
        try:
            wrep = WhatsAppReporter(config)
            wrep.send_whatsapp(scored_df, date_str)
        except Exception as e:
            logger.error(f"WhatsApp failed: {e}")

    logger.info("=" * 60)
    logger.info("ADVANCED ANALYSIS COMPLETE")
    logger.info("=" * 60)
    logger.info(
        f"Total: {len(scored_df)} | STRONG BUY: {len(scored_df[scored_df['Rating'] == 'STRONG BUY'])} "
        f"| BUY: {len(scored_df[scored_df['Rating'] == 'BUY'])}"
    )
    logger.info(f"Dashboard: {dashboard_path or 'N/A'} | CSV: {csv_path}")

if __name__ == "__main__":
    try:
        run_daily_analysis()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
