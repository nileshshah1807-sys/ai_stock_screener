"""Alternative data, technical indicators, caches, and backtesting."""

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .runtime import Config

logger = logging.getLogger(__name__)

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
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
        avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
        return rsi.mask((avg_loss == 0) & (avg_gain == 0), 50.0)

    @staticmethod
    def calculate_adx(high, low, close, window=14):
        """Proper Wilder ADX. Returns (adx, plus_di, minus_di) - ADX alone only
        measures trend STRENGTH, not direction (a strong downtrend produces just
        as high a reading as a strong uptrend), so callers that want to reward
        "strong trend" only for uptrends need +DI/-DI too."""
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
            plus_di_val = plus_di.iloc[-1]
            minus_di_val = minus_di.iloc[-1]
            return (
                float(val) if not pd.isna(val) else 25.0,
                float(plus_di_val) if not pd.isna(plus_di_val) else 25.0,
                float(minus_di_val) if not pd.isna(minus_di_val) else 25.0,
            )
        except Exception:
            return 25.0, 25.0, 25.0

    @staticmethod
    def calculate_stoch_rsi(close, window=14, k_window=3):
        """Return the smoothed StochRSI %K, not the underlying RSI value."""
        try:
            rsi_series = TechnicalEnhancer._rsi(close.astype(float), window)
            rsi_min = rsi_series.rolling(window).min()
            rsi_max = rsi_series.rolling(window).max()
            raw_stoch = ((rsi_series - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)) * 100
            stoch_k = raw_stoch.rolling(k_window, min_periods=k_window).mean()
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
    # Columns that must exist in the cache schema. If a cache file predates one
    # of these (e.g. was written before Avg_Turnover_INR was added), every row
    # in it is missing that data and any filter relying on it would silently
    # drop everything - so treat such a cache as stale and force a refresh.
    REQUIRED_COLUMNS = (
        "Avg_Turnover_INR", "MA50_Slope_Pct", "ADX_Plus_DI", "ADX_Minus_DI",
        "Technical_Indicator_Version",
    )

    @staticmethod
    def save(cache_path, records):
        try:
            pd.DataFrame(records).to_csv(cache_path, index=False)
        except Exception as e:
            logger.warning(f"Price cache save failed: {e}")

    @staticmethod
    def load(cache_path, max_age_hours=18):
        """Return cached DataFrame only if the file is fresh enough and has the
        expected schema."""
        try:
            p = Path(cache_path)
            if not p.exists():
                return pd.DataFrame()
            age_hours = (time.time() - p.stat().st_mtime) / 3600
            if age_hours > max_age_hours:
                logger.info(f"Price cache is {age_hours:.1f}h old (> {max_age_hours}h) - ignoring")
                return pd.DataFrame()
            df = pd.read_csv(p)
            missing_columns = [c for c in PriceCache.REQUIRED_COLUMNS if c not in df.columns]
            if missing_columns and not df.empty:
                logger.info(
                    f"Price cache is missing columns {missing_columns} - "
                    "ignoring and forcing a one-off full refresh."
                )
                return pd.DataFrame()
            return df
        except Exception:
            return pd.DataFrame()

# =====================================================
# BACKTEST ENGINE
# =====================================================
class BacktestEngine:
    """Log score snapshots and measure realized forward returns by rating."""
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
            if "Final_Score" in scored_df:
                snapshot["Final_Score"] = scored_df["Final_Score"]
            snapshot["Run_Date"] = date_str
            snapshot["Forward_Return_Pct"] = np.nan
            if self.history_file.exists():
                existing = pd.read_csv(self.history_file)
                # drop any earlier rows from the same run date, then append
                existing = existing[existing["Run_Date"] != date_str]
                combined = pd.concat([existing, snapshot], ignore_index=True)
            else:
                combined = snapshot

            # Fill each position once, on the first available snapshot at or
            # beyond the requested horizon. This produces an actual out-of-
            # sample price return rather than circularly averaging model scores.
            run_dates = pd.to_datetime(combined["Run_Date"], dayfirst=True, errors="coerce")
            current_prices = snapshot.set_index("Symbol")["Current_Price"]
            horizon = int(getattr(Config, "BACKTEST_HORIZON_DAYS", 30))
            eligible = (
                combined["Forward_Return_Pct"].isna()
                & run_dates.notna()
                & ((datetime.now() - run_dates).dt.days >= horizon)
                & combined["Symbol"].isin(current_prices.index)
            )
            if eligible.any():
                entry_price = pd.to_numeric(combined.loc[eligible, "Current_Price"], errors="coerce")
                exit_price = combined.loc[eligible, "Symbol"].map(current_prices)
                valid_prices = entry_price > 0
                combined.loc[eligible, "Forward_Return_Pct"] = np.where(
                    valid_prices,
                    ((exit_price / entry_price) - 1) * 100,
                    np.nan,
                )
            combined.to_csv(self.history_file, index=False)
            logger.info(f"Backtest log saved: {len(combined)} total records")
        except Exception as e:
            logger.warning(f"Backtest logging failed: {e}")

    def analyze_performance(self):
        try:
            if not self.history_file.exists():
                return None
            df = pd.read_csv(self.history_file)
            if "Forward_Return_Pct" not in df:
                return None
            realized = df.dropna(subset=["Forward_Return_Pct"])
            if realized.empty:
                return None
            return realized.groupby("Rating")["Forward_Return_Pct"].agg(
                observations="count",
                average_return_pct="mean",
                median_return_pct="median",
                hit_rate_pct=lambda returns: (returns > 0).mean() * 100,
            ).round(2).to_dict("index")
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
