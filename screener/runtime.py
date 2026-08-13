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
    # Model and policy versions are deliberately separate from the report schema.
    # Any semantic ranking change must bump MODEL_VERSION; additive audit columns
    # bump OUTPUT_SCHEMA_VERSION without pretending the signal itself changed.
    MODEL_VERSION = os.getenv("MODEL_VERSION", "4.0.0-candidate")
    RECOMMENDATION_POLICY_VERSION = os.getenv(
        "RECOMMENDATION_POLICY_VERSION", "4.0.0-candidate"
    )
    OUTPUT_SCHEMA_VERSION = os.getenv("OUTPUT_SCHEMA_VERSION", "4.1.0")
    MODEL_VALIDATION_STATUS = os.getenv(
        "MODEL_VALIDATION_STATUS",
        "Research model; point-in-time out-of-sample validation pending",
    )
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
    FUND_CACHE_MAX_AGE_DAYS = _env_int("FUND_CACHE_MAX_AGE_DAYS", 7)
    ANALYSIS_TIMEZONE = os.getenv("ANALYSIS_TIMEZONE", "Asia/Kolkata")
    MARKET_BAR_COMPLETE_AFTER_IST = os.getenv(
        "MARKET_BAR_COMPLETE_AFTER_IST", "16:15"
    )
    # Fail closed after the completion cutoff if a normal weekday has no
    # same-session bar. Populate official weekday exchange holidays as ISO dates.
    NSE_MARKET_HOLIDAYS = _env_list("NSE_MARKET_HOLIDAYS", [])
    NSE_MARKET_CALENDAR_VERSION = os.getenv(
        "NSE_MARKET_CALENDAR_VERSION",
        "unconfigured-local-calendar",
    )
    ALLOW_PROVISIONAL_MARKET_BARS = _env_bool(
        "ALLOW_PROVISIONAL_MARKET_BARS", False
    )

    # --- P3: liquidity pre-filter (applied before the slow fundamentals stage) ---
    LIQUIDITY_FILTER_ENABLED = _env_bool("LIQUIDITY_FILTER_ENABLED", True)
    # In v4 liquidity is an execution overlay, not a research-universe selector.
    # Set this legacy escape hatch only when runtime/API constraints make a full
    # research pass impossible; the output then names itself as filtered.
    PREFILTER_RESEARCH_UNIVERSE_BY_LIQUIDITY = _env_bool(
        "PREFILTER_RESEARCH_UNIVERSE_BY_LIQUIDITY", False
    )
    MIN_PRICE_INR = _env_float("MIN_PRICE_INR", 0.0)          # drop penny stocks
    # Rupee-value average daily turnover (Avg_Volume * Current_Price), not just a raw
    # share count - a 50-lakh turnover bar is a much more meaningful liquidity floor
    # across price points than a fixed share count.
    MIN_AVG_TURNOVER_INR = _env_float("MIN_AVG_TURNOVER_INR", 50_00_000.0)  # Rs 50 lakh/day
    # A median of actual daily Close * Volume is resistant to block trades and
    # one-day spikes. Keep the broad-universe floor permissive; a stricter
    # high-conviction gate is applied after scoring.
    MIN_MEDIAN_TURNOVER_20D_INR = _env_float(
        "MIN_MEDIAN_TURNOVER_20D_INR", 50_00_000.0
    )
    # Execution is position-size dependent. NSE's monthly Group I/II/III file
    # supplies six-month trading-frequency and mean impact-cost evidence for a
    # Rs1 lakh order. Median turnover is only a proxy for custom/larger sizes.
    NSE_LIQUIDITY_ENABLED = _env_bool("NSE_LIQUIDITY_ENABLED", True)
    NSE_LIQUIDITY_CACHE_MAX_AGE_DAYS = _env_int(
        "NSE_LIQUIDITY_CACHE_MAX_AGE_DAYS", 35
    )
    NSE_LIQUIDITY_TIMEOUT_SECONDS = _env_int(
        "NSE_LIQUIDITY_TIMEOUT_SECONDS", 20
    )
    PORTFOLIO_TARGET_POSITION_INR = _env_float(
        "PORTFOLIO_TARGET_POSITION_INR", 1_00_000.0
    )
    LIQUIDITY_POSITION_PARTICIPATION_RATE = _env_float(
        "LIQUIDITY_POSITION_PARTICIPATION_RATE", 0.01
    )
    LIQUIDITY_MIN_TRADING_FREQUENCY = _env_float(
        "LIQUIDITY_MIN_TRADING_FREQUENCY", 0.80
    )
    LIQUIDITY_MAX_TURNOVER_TOP5_SHARE = _env_float(
        "LIQUIDITY_MAX_TURNOVER_TOP5_SHARE", 0.50
    )

    # --- P2: data-completeness gate ---
    FUNDAMENTAL_MIN_COVERAGE_FOR_BUY = _env_float(
        "FUNDAMENTAL_MIN_COVERAGE_FOR_BUY", 0.55
    )
    FUNDAMENTAL_MIN_COVERAGE_FOR_STRONG_BUY = _env_float(
        "FUNDAMENTAL_MIN_COVERAGE_FOR_STRONG_BUY", 0.75
    )
    TECHNICAL_MIN_COVERAGE_FOR_BUY = _env_float(
        "TECHNICAL_MIN_COVERAGE_FOR_BUY", 0.75
    )
    TECHNICAL_MIN_COVERAGE_FOR_STRONG_BUY = _env_float(
        "TECHNICAL_MIN_COVERAGE_FOR_STRONG_BUY", 0.90
    )

    # A valuation/fundamental score may identify a research candidate, but BUY
    # still requires a constructive medium-term chart.
    REQUIRE_UPTREND_FOR_BUY = _env_bool("REQUIRE_UPTREND_FOR_BUY", True)
    BUY_MIN_MA50_SLOPE = _env_float("BUY_MIN_MA50_SLOPE", 0.0)
    BUY_MIN_3M_RETURN = _env_float("BUY_MIN_3M_RETURN", 0.0)
    # A row measured on an older session cannot be compared with the rest of the
    # cross-section, so it is published but cannot hold BUY conviction. Disable
    # only if you accept mixed measurement dates inside one ranking.
    REQUIRE_ALIGNED_PRICE_BAR_FOR_BUY = _env_bool(
        "REQUIRE_ALIGNED_PRICE_BAR_FOR_BUY", True
    )

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

    # Audit-only stability bands. They do not change a rating; they identify
    # observations close enough to a hard policy boundary that a small data
    # revision could flip the label. Widths must be validated before any future
    # stateful hysteresis policy is enabled.
    BORDERLINE_SCORE_BAND = _env_float("BORDERLINE_SCORE_BAND", 1.0)
    BORDERLINE_PRICE_MA50_PCT_BAND = _env_float(
        "BORDERLINE_PRICE_MA50_PCT_BAND", 1.0
    )
    BORDERLINE_MA50_SLOPE_PCT_BAND = _env_float(
        "BORDERLINE_MA50_SLOPE_PCT_BAND", 0.25
    )
    BORDERLINE_3M_RETURN_PCT_BAND = _env_float(
        "BORDERLINE_3M_RETURN_PCT_BAND", 1.0
    )
    BORDERLINE_GROWTH_RATIO_BAND = _env_float(
        "BORDERLINE_GROWTH_RATIO_BAND", 0.01
    )
    BORDERLINE_ADX_BAND = _env_float("BORDERLINE_ADX_BAND", 1.0)
    BORDERLINE_DI_BAND = _env_float("BORDERLINE_DI_BAND", 1.0)
    BORDERLINE_TECH_SCORE_BAND = _env_float(
        "BORDERLINE_TECH_SCORE_BAND", 2.0
    )
    BORDERLINE_COVERAGE_BAND = _env_float("BORDERLINE_COVERAGE_BAND", 0.05)

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
    REVERSE_DCF_DISCOUNT_RATE = _env_float("REVERSE_DCF_DISCOUNT_RATE", 0.11)          # required equity return for the Yahoo FCF proxy
    REVERSE_DCF_TERMINAL_GROWTH = _env_float("REVERSE_DCF_TERMINAL_GROWTH", 0.04)       # fixed terminal growth for implied FCF CAGR
    REVERSE_DCF_FCF_MARGIN_FALLBACK = _env_float("REVERSE_DCF_FCF_MARGIN_FALLBACK", 0.08)   # used only when FCF is missing but revenue exists
    REVERSE_DCF_MIN_GROWTH = _env_float("REVERSE_DCF_MIN_GROWTH", -0.30)
    REVERSE_DCF_MAX_GROWTH = _env_float("REVERSE_DCF_MAX_GROWTH", 0.60)
    REVERSE_DCF_MIN_TERMINAL_GROWTH = _env_float("REVERSE_DCF_MIN_TERMINAL_GROWTH", -0.05)
    REVERSE_DCF_MAX_TERMINAL_GROWTH = _env_float("REVERSE_DCF_MAX_TERMINAL_GROWTH", 0.09)
    REVERSE_DCF_MIN_VALID_FCF_YIELD = _env_float("REVERSE_DCF_MIN_VALID_FCF_YIELD", 0.005)
    REVERSE_DCF_RANKING_WEIGHT = _env_float("REVERSE_DCF_RANKING_WEIGHT", 0.10)
    CAP_STRONG_BUY_ON_REPORTED_NEGATIVE_FCF = _env_bool(
        "CAP_STRONG_BUY_ON_REPORTED_NEGATIVE_FCF", True
    )
    # Smooth score mapping and neutral band for the single independent
    # value-to-market signal. These replace stacked threshold bonuses.
    REVERSE_DCF_SCORE_LOG_SCALE = _env_float(
        "REVERSE_DCF_SCORE_LOG_SCALE", 1.0
    )
    REVERSE_DCF_NEUTRAL_LOG_BAND = _env_float(
        "REVERSE_DCF_NEUTRAL_LOG_BAND", 0.05
    )

    # --- Earnings transcript sentiment ---
    TRANSCRIPT_SENTIMENT_ENABLED = _env_bool("TRANSCRIPT_SENTIMENT_ENABLED", True)
    TRANSCRIPT_SENTIMENT_WEIGHT = _env_float("TRANSCRIPT_SENTIMENT_WEIGHT", 0.15)
    REQUIRE_TRANSCRIPT_FOR_STRONG_BUY = _env_bool("REQUIRE_TRANSCRIPT_FOR_STRONG_BUY", False)
    TRANSCRIPT_MAX_EVIDENCE_AGE_DAYS = _env_int("TRANSCRIPT_MAX_EVIDENCE_AGE_DAYS", 180)
    TRANSCRIPT_MIN_PRIORITY_SCORE = _env_float("TRANSCRIPT_MIN_PRIORITY_SCORE", 55.0)
    TRANSCRIPT_MAX_PRIORITY_RISK = _env_float("TRANSCRIPT_MAX_PRIORITY_RISK", 60.0)
    TRANSCRIPT_RECENCY_HALF_LIFE_DAYS = _env_float(
        "TRANSCRIPT_RECENCY_HALF_LIFE_DAYS", 90.0
    )
    TRANSCRIPT_CYCLE_TAPER_DAYS = _env_int(
        "TRANSCRIPT_CYCLE_TAPER_DAYS", 20
    )
    TRANSCRIPT_FAIL_ON_ERROR = _env_bool("TRANSCRIPT_FAIL_ON_ERROR", True)
    # Shadow mode: adds evidence columns only and never mutates score/rating.
    RED_FLAG_ENRICHMENT_ENABLED = _env_bool("RED_FLAG_ENRICHMENT_ENABLED", False)
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    # Validation runs read cached transcript sentiment but must not mutate it.
    SUPABASE_READ_ONLY = _env_bool("SUPABASE_READ_ONLY", False)
    SUPABASE_TIMEOUT_SECONDS = _env_int("SUPABASE_TIMEOUT_SECONDS", 30)

    # =================================================================
    # Model 5.0 factor architecture (candidate; disabled by default)
    # =================================================================
    # The 4.x core score blends one undifferentiated fundamental block with ten
    # partly-redundant technical components. Model 5.0 separates the economic
    # concepts (quality, growth, value, momentum, risk) and demotes the
    # short-horizon indicators to entry-timing diagnostics. It is gated because
    # it re-ranks the universe: promote it only after the candidate-validation
    # workflow has compared it against the 4.x baseline on identical inputs.
    FACTOR_MODEL_ENABLED = _env_bool("FACTOR_MODEL_ENABLED", False)
    FACTOR_WEIGHT_QUALITY = _env_float("FACTOR_WEIGHT_QUALITY", 0.35)
    FACTOR_WEIGHT_GROWTH = _env_float("FACTOR_WEIGHT_GROWTH", 0.20)
    FACTOR_WEIGHT_VALUE = _env_float("FACTOR_WEIGHT_VALUE", 0.15)
    FACTOR_WEIGHT_MOMENTUM = _env_float("FACTOR_WEIGHT_MOMENTUM", 0.25)
    FACTOR_WEIGHT_RISK = _env_float("FACTOR_WEIGHT_RISK", 0.05)
    # Rank each factor inside its own sector where the sector has enough usable
    # peers. A utility and a software company do not share a normal ROIC, growth
    # rate, or earnings yield, so a single market-wide percentile would encode a
    # sector bet as if it were stock selection.
    FACTOR_SECTOR_NEUTRAL = _env_bool("FACTOR_SECTOR_NEUTRAL", True)
    FACTOR_MIN_SECTOR_PEERS = _env_int("FACTOR_MIN_SECTOR_PEERS", 8)
    # Cross-sectional winsorization before ranking. Ranks are already robust to
    # outliers; this bounds the derived ratios that feed continuous sub-scores.
    FACTOR_WINSOR_LOWER_PCT = _env_float("FACTOR_WINSOR_LOWER_PCT", 0.05)
    FACTOR_WINSOR_UPPER_PCT = _env_float("FACTOR_WINSOR_UPPER_PCT", 0.95)
    # A cheap multiple on a low-quality business is the classic value trap. Cap
    # the value contribution rather than deleting it, so the evidence stays
    # visible in the export.
    FACTOR_VALUE_QUALITY_FLOOR_PCT = _env_float(
        "FACTOR_VALUE_QUALITY_FLOOR_PCT", 30.0
    )
    FACTOR_VALUE_CEILING_WHEN_LOW_QUALITY = _env_float(
        "FACTOR_VALUE_CEILING_WHEN_LOW_QUALITY", 50.0
    )
    # A factor block computed from almost no observed inputs is not evidence.
    # Below this the block is published but shrunk toward neutral 50.
    FACTOR_MIN_BLOCK_COVERAGE = _env_float("FACTOR_MIN_BLOCK_COVERAGE", 0.50)
    # Publish the blended score as its cross-sectional percentile. Averaging
    # five already-uniform percentile blocks concentrates the result around 50,
    # which leaves the 70/60/50/40 rating bands -- calibrated for the 4.x
    # absolute score -- effectively unreachable. Ranking the blend restores
    # them: >=70 is the top 30% of the cross-section. Model 5.0 ratings are
    # therefore relative; the absolute protection is the regime overlay plus the
    # hard trend, quality and liquidity gates.
    FACTOR_SCORE_AS_PERCENTILE = _env_bool("FACTOR_SCORE_AS_PERCENTILE", True)

    # --- Price history depth -------------------------------------------------
    # 12-1 momentum needs ~273 sessions, a rising-MA200 test needs ~220. The
    # legacy 6-month window cannot express either. Features that are defined on
    # a six-month window (6M return/high/low, average turnover) stay pinned to
    # LEGACY_HISTORY_WINDOW_SESSIONS so lengthening this does not silently
    # redefine them.
    PRICE_HISTORY_PERIOD = os.getenv("PRICE_HISTORY_PERIOD", "2y")
    LEGACY_HISTORY_WINDOW_SESSIONS = _env_int(
        "LEGACY_HISTORY_WINDOW_SESSIONS", 126
    )
    MIN_PRICE_SESSIONS_REQUIRED = _env_int("MIN_PRICE_SESSIONS_REQUIRED", 60)

    # --- Benchmark, relative strength and market regime ----------------------
    # Nifty 500 (^CRSLDX) is the broadest liquid total-market proxy Yahoo serves
    # for India; ^NSEI is the fallback when it is unavailable.
    BENCHMARK_INDEX_SYMBOL = os.getenv("BENCHMARK_INDEX_SYMBOL", "^CRSLDX")
    BENCHMARK_INDEX_FALLBACK = os.getenv("BENCHMARK_INDEX_FALLBACK", "^NSEI")
    MARKET_REGIME_ENABLED = _env_bool("MARKET_REGIME_ENABLED", True)
    # The regime overlay changes deployment conviction only. It never edits a
    # factor score, so the underlying research rank stays visible in RISK_OFF.
    MARKET_REGIME_MA_SESSIONS = _env_int("MARKET_REGIME_MA_SESSIONS", 200)
    MARKET_REGIME_SLOPE_SESSIONS = _env_int("MARKET_REGIME_SLOPE_SESSIONS", 20)
    MARKET_REGIME_NEUTRAL_BAND_PCT = _env_float(
        "MARKET_REGIME_NEUTRAL_BAND_PCT", 2.0
    )
    REGIME_RISK_OFF_DISABLES_STRONG_BUY = _env_bool(
        "REGIME_RISK_OFF_DISABLES_STRONG_BUY", True
    )
    REGIME_RISK_OFF_MIN_MOMENTUM_PCT = _env_float(
        "REGIME_RISK_OFF_MIN_MOMENTUM_PCT", 90.0
    )
    REGIME_NEUTRAL_MIN_MOMENTUM_PCT_FOR_STRONG_BUY = _env_float(
        "REGIME_NEUTRAL_MIN_MOMENTUM_PCT_FOR_STRONG_BUY", 85.0
    )

    # --- MA200 trend gate with hysteresis ------------------------------------
    # An exact one-rupee boundary makes a stock oscillating around its average
    # flip rating daily. The BUY test therefore uses a tolerance band and the
    # SELL side requires a confirmed, persistent breakdown instead.
    REQUIRE_MA200_TREND_FOR_BUY = _env_bool("REQUIRE_MA200_TREND_FOR_BUY", True)
    BUY_MA200_TOLERANCE = _env_float("BUY_MA200_TOLERANCE", 0.98)
    BUY_MIN_MA200_SLOPE_PCT = _env_float("BUY_MIN_MA200_SLOPE_PCT", 0.0)
    STRONG_BUY_REQUIRE_MA50_ABOVE_MA200 = _env_bool(
        "STRONG_BUY_REQUIRE_MA50_ABOVE_MA200", True
    )
    STRONG_BUY_MIN_RS_6M = _env_float("STRONG_BUY_MIN_RS_6M", 0.0)
    STRONG_BUY_MIN_RS_12M = _env_float("STRONG_BUY_MIN_RS_12M", 0.0)
    BUY_MIN_RS_6M = _env_float("BUY_MIN_RS_6M", 0.0)
    # Confirmed-breakdown hysteresis for the downgrade side.
    BREAKDOWN_CONFIRM_SESSIONS = _env_int("BREAKDOWN_CONFIRM_SESSIONS", 10)
    # Percentile gates on the factor blocks themselves.
    BUY_MIN_QUALITY_PCT = _env_float("BUY_MIN_QUALITY_PCT", 40.0)
    STRONG_BUY_MIN_QUALITY_PCT = _env_float("STRONG_BUY_MIN_QUALITY_PCT", 70.0)
    STRONG_BUY_MIN_GROWTH_PCT = _env_float("STRONG_BUY_MIN_GROWTH_PCT", 60.0)
    STRONG_BUY_MIN_MOMENTUM_PCT = _env_float("STRONG_BUY_MIN_MOMENTUM_PCT", 70.0)
    # Model 5.0 tightens the BUY coverage floors the proposal calls out.
    FACTOR_FUNDAMENTAL_MIN_COVERAGE_FOR_BUY = _env_float(
        "FACTOR_FUNDAMENTAL_MIN_COVERAGE_FOR_BUY", 0.70
    )
    FACTOR_TECHNICAL_MIN_COVERAGE_FOR_BUY = _env_float(
        "FACTOR_TECHNICAL_MIN_COVERAGE_FOR_BUY", 0.90
    )
    # Execution liquidity as a BUY requirement, not only an Actionable_Rank
    # overlay. Research_Rating stays uncapped so the research view is preserved.
    REQUIRE_LIQUIDITY_FOR_BUY = _env_bool("REQUIRE_LIQUIDITY_FOR_BUY", True)
    # Gross NPA, net NPA, capital adequacy and solvency are declared as
    # required specialist evidence but NO collector in this repository ever
    # populates them -- Yahoo does not publish them. The practical effect is
    # that every bank, NBFC and insurer is permanently barred from BUY, which
    # silently removes the single largest sector of the Indian market from the
    # actionable universe.
    #
    # Model 5.0 scores financials on the statement evidence that IS reported
    # (return on equity/assets, equity-to-assets, margin, earnings stability),
    # at full coverage. Setting this True accepts that template as sufficient
    # for BUY and keeps the regulatory-evidence requirement for STRONG BUY
    # only. It defaults False so the existing fail-closed behaviour is
    # preserved until this is a deliberate, reviewed decision.
    FACTOR_FINANCIAL_STATEMENT_QUALITY_SUFFICIENT = _env_bool(
        "FACTOR_FINANCIAL_STATEMENT_QUALITY_SUFFICIENT", False
    )
    # Rank capped candidates by eligibility class then research score, instead
    # of letting every gate failure collapse onto an identical 59.99.
    RANK_BY_ELIGIBILITY_CLASS = _env_bool("RANK_BY_ELIGIBILITY_CLASS", True)

    # --- Financial-statement collection (Model 5.0 inputs) -------------------
    # Yahoo's quote metadata has no total assets, EBIT, gross profit, cash flow
    # history, or multi-year series, and it omits ROE/ROA outright for part of
    # the universe. Quality, growth and accrual evidence therefore require the
    # annual statements. They restate quarterly at most, so the cache TTL is
    # long and the steady-state fetch cost is near zero.
    STATEMENT_COLLECTION_ENABLED = _env_bool("STATEMENT_COLLECTION_ENABLED", True)
    STATEMENT_CACHE_MAX_AGE_DAYS = _env_int("STATEMENT_CACHE_MAX_AGE_DAYS", 90)
    STATEMENT_FETCH_MAX_SYMBOLS_PER_RUN = _env_int(
        "STATEMENT_FETCH_MAX_SYMBOLS_PER_RUN", 400
    )
    STATEMENT_REQUESTS_PER_MINUTE = _env_int("STATEMENT_REQUESTS_PER_MINUTE", 40)
    STATEMENT_MIN_YEARS_FOR_CAGR = _env_int("STATEMENT_MIN_YEARS_FOR_CAGR", 4)

    # A snapshot score is not a backtest. Measure the realized return after a
    # fixed holding period before making any claim about rating performance.
    BACKTEST_HORIZON_DAYS = _env_int("BACKTEST_HORIZON_DAYS", 30)
    BACKTEST_WRITES_ENABLED = _env_bool("BACKTEST_WRITES_ENABLED", True)
    RUN_MANIFEST_ENABLED = _env_bool("RUN_MANIFEST_ENABLED", True)

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
            value = getattr(config_local, key)
            if key in {"OUTPUT_DIR", "YFINANCE_CACHE_DIR"}:
                value = Path(value)
            setattr(config_class, key, value)
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
