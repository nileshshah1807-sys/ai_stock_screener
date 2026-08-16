"""Alternative data, technical indicators, caches, and backtesting."""

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from .runtime import Config

logger = logging.getLogger(__name__)


def normalize_market_holidays(values):
    """Return configured exchange holidays as validated ``date`` objects."""

    if values is None:
        return frozenset()
    if isinstance(values, str):
        values = values.split(",")
    holidays = set()
    for value in values:
        try:
            holidays.add(pd.Timestamp(str(value).strip()).date())
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid NSE market holiday %r", value)
    return frozenset(holidays)


def is_expected_nse_session(day, market_holidays=()):
    """Whether a normal NSE cash-market daily bar is expected for ``day``."""

    return day.weekday() < 5 and day not in normalize_market_holidays(
        market_holidays
    )


def expected_sessions_behind(bar_date, expected_session, market_holidays=()):
    """How many expected NSE sessions ``bar_date`` lags ``expected_session``.

    0 means aligned. A positive count is the real staleness of the observation
    and must be exported rather than left null, so a lagging bar can never be
    mistaken for a current one.
    """

    if bar_date is None or expected_session is None:
        return None
    if bar_date >= expected_session:
        return 0
    behind = 0
    candidate = bar_date + timedelta(days=1)
    while candidate <= expected_session:
        if is_expected_nse_session(candidate, market_holidays):
            behind += 1
        candidate += timedelta(days=1)
    return behind


def latest_expected_completed_nse_session(
    day, current_time, completion_cutoff, market_holidays=()
):
    """Latest regular NSE session whose daily bar should be complete."""

    candidate = day
    if (
        not is_expected_nse_session(candidate, market_holidays)
        or current_time < completion_cutoff
    ):
        candidate = candidate - pd.Timedelta(days=1)
        if hasattr(candidate, "date"):
            candidate = candidate.date()
    while not is_expected_nse_session(candidate, market_holidays):
        candidate = candidate - pd.Timedelta(days=1)
        if hasattr(candidate, "date"):
            candidate = candidate.date()
    return candidate

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
    # Increment whenever indicator semantics change so cached rows cannot mix
    # fabricated defaults from an older model with explicit missing evidence.
    # ``INDICATOR_VERSION`` remains the public/default 4.x contract. Model 5.0
    # deliberately uses a separate version because its two-year input history
    # changes the initialization of EWM-based legacy indicators in addition to
    # adding long-trend, momentum and downside-risk fields. Keeping the two
    # contracts distinct lets a disabled factor model reuse the exact v6 cache
    # that production already has, while an enabled candidate refreshes to v7.
    INDICATOR_VERSION = 6
    FACTOR_INDICATOR_VERSION = 7

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
            raw_plus_dm = high.diff()
            raw_minus_dm = -low.diff()
            plus_dm = raw_plus_dm.where((raw_plus_dm > raw_minus_dm) & (raw_plus_dm > 0), 0.0)
            minus_dm = raw_minus_dm.where((raw_minus_dm > raw_plus_dm) & (raw_minus_dm > 0), 0.0)
            tr = pd.concat(
                [
                    high - low,
                    (high - close.shift(1)).abs(),
                    (low - close.shift(1)).abs(),
                ],
                axis=1,
            ).max(axis=1)
            atr = tr.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
            smoothed_plus_dm = plus_dm.ewm(
                alpha=1 / window, adjust=False, min_periods=window
            ).mean()
            smoothed_minus_dm = minus_dm.ewm(
                alpha=1 / window, adjust=False, min_periods=window
            ).mean()
            plus_di = 100 * smoothed_plus_dm / atr.where(atr.ne(0))
            minus_di = 100 * smoothed_minus_dm / atr.where(atr.ne(0))
            # A sufficiently long, genuinely flat series has zero directional
            # movement, not missing data. Keep that legitimate zero while short
            # or otherwise invalid histories remain NaN.
            plus_di = plus_di.where(~atr.eq(0), 0.0)
            minus_di = minus_di.where(~atr.eq(0), 0.0)
            di_sum = plus_di + minus_di
            dx = 100 * (plus_di - minus_di).abs() / di_sum.where(di_sum.ne(0))
            dx = dx.where(~di_sum.eq(0), 0.0)
            adx = dx.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
            val = adx.iloc[-1]
            plus_di_val = plus_di.iloc[-1]
            minus_di_val = minus_di.iloc[-1]
            if any(pd.isna(value) for value in (val, plus_di_val, minus_di_val)):
                return np.nan, np.nan, np.nan
            return float(val), float(plus_di_val), float(minus_di_val)
        except Exception:
            return np.nan, np.nan, np.nan

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
            return float(val) if not pd.isna(val) else np.nan
        except Exception:
            return np.nan

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
            atr = tr.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
            val = atr.iloc[-1]
            return float(val) if not pd.isna(val) else np.nan
        except Exception:
            return np.nan

    @staticmethod
    def calculate_pct_return(close, lookback_sessions):
        """Return an adjusted-close percentage change or explicit missing.

        A real unchanged price is exactly ``0.0``. Insufficient history and
        invalid/nonpositive endpoints are unknown evidence and therefore NaN.
        """
        try:
            values = pd.to_numeric(close, errors="coerce")
            lookback_sessions = int(lookback_sessions)
            if lookback_sessions <= 0 or len(values) <= lookback_sessions:
                return np.nan
            current = float(values.iloc[-1])
            prior = float(values.iloc[-(lookback_sessions + 1)])
            if not np.isfinite(current) or not np.isfinite(prior) or prior <= 0:
                return np.nan
            return (current / prior - 1.0) * 100.0
        except (TypeError, ValueError, IndexError):
            return np.nan

    @staticmethod
    def skip_month_return(close, sessions, skip=21):
        """Formation return ending ``skip`` sessions ago.

        Momentum research measures the prior 3-12 month performance while
        deliberately excluding the most recent month, because short-horizon
        reversal and single-event noise dominate that last stretch and work
        against the medium-term signal.
        """
        try:
            values = pd.to_numeric(close, errors="coerce").dropna()
            sessions, skip = int(sessions), int(skip)
            if sessions <= skip or len(values) <= sessions:
                return np.nan
            latest = float(values.iloc[-(skip + 1)])
            prior = float(values.iloc[-(sessions + 1)])
            if not np.isfinite(latest) or not np.isfinite(prior) or prior <= 0:
                return np.nan
            return (latest / prior - 1.0) * 100.0
        except (TypeError, ValueError, IndexError):
            return np.nan


def calculate_trend_risk_features(closes, opens=None, sessions_per_year=252):
    """Long-trend, medium-momentum and downside-risk features.

    All inputs are split/dividend-adjusted closes on the same scale as
    ``Technical_Price``. Every output is explicitly NaN when its lookback is not
    fully available: a partially observed 200-day average is not a 200-day
    average, and silently substituting a shorter window would make an
    under-seasoned listing look like an established uptrend.
    """
    out = {
        "MA200": np.nan,
        "MA200_Slope_Pct": np.nan,
        "Price_To_MA200_Pct": np.nan,
        "MA50_To_MA200_Pct": np.nan,
        "Sessions_Above_MA200_Share": np.nan,
        "Below_MA200_Streak": np.nan,
        "Momentum_12_1_Pct": np.nan,
        "Momentum_6_1_Pct": np.nan,
        "Pct_Change_12M": np.nan,
        "Volatility_Ann_Pct": np.nan,
        "Downside_Deviation_Pct": np.nan,
        "Max_Drawdown_1Y_Pct": np.nan,
        "Gap_Risk_Pct": np.nan,
        "Return_Concentration_1Y": np.nan,
        "Trend_Quality_R2": np.nan,
        "Price_History_Sessions": 0,
    }
    values = pd.to_numeric(pd.Series(closes), errors="coerce").dropna()
    values = values[values > 0]
    if values.empty:
        return out
    out["Price_History_Sessions"] = int(len(values))
    price = float(values.iloc[-1])

    # --- long-term trend structure -----------------------------------------
    if len(values) >= 200:
        ma200_series = values.rolling(200).mean()
        ma200 = float(ma200_series.iloc[-1])
        if np.isfinite(ma200) and ma200 > 0:
            out["MA200"] = round(ma200, 2)
            out["Price_To_MA200_Pct"] = round((price / ma200 - 1.0) * 100.0, 3)
            if len(ma200_series) >= 221 and np.isfinite(ma200_series.iloc[-21]):
                prior = float(ma200_series.iloc[-21])
                if prior > 0:
                    out["MA200_Slope_Pct"] = round((ma200 / prior - 1.0) * 100.0, 4)
            if len(values) >= 250:
                ma50_now = float(values.rolling(50).mean().iloc[-1])
                if np.isfinite(ma50_now):
                    out["MA50_To_MA200_Pct"] = round(
                        (ma50_now / ma200 - 1.0) * 100.0, 3
                    )
            # Mask sessions with no 200-day average yet. A bare ``>`` against
            # NaN yields False, which would report "closed below its average"
            # for the first 199 sessions when the truth is that the average did
            # not exist -- understating the share for every recently listed name.
            above = (values > ma200_series).where(ma200_series.notna())
            recent = above.iloc[-126:].dropna()
            if len(recent) >= 60:
                out["Sessions_Above_MA200_Share"] = round(float(recent.mean()), 4)
            # Consecutive completed sessions closing below the average. The
            # downgrade side uses this so one dip through the line cannot flip a
            # rating that a rebound would flip straight back.
            below = (above == False).fillna(False).to_numpy()  # noqa: E712
            streak = 0
            for flag in below[::-1]:
                if not flag:
                    break
                streak += 1
            out["Below_MA200_Streak"] = int(streak)

    # --- medium-term momentum ----------------------------------------------
    out["Momentum_12_1_Pct"] = TechnicalEnhancer.skip_month_return(values, 252)
    out["Momentum_6_1_Pct"] = TechnicalEnhancer.skip_month_return(values, 126)
    out["Pct_Change_12M"] = TechnicalEnhancer.calculate_pct_return(values, 252)

    # --- risk ---------------------------------------------------------------
    window = values.iloc[-(sessions_per_year + 1):]
    returns = window.pct_change().dropna()
    if len(returns) >= 60:
        annualizer = float(np.sqrt(sessions_per_year))
        volatility = float(returns.std(ddof=1))
        if np.isfinite(volatility):
            out["Volatility_Ann_Pct"] = round(volatility * annualizer * 100.0, 3)
        downside = returns[returns < 0]
        if len(downside) >= 20:
            deviation = float(downside.std(ddof=1))
            if np.isfinite(deviation):
                out["Downside_Deviation_Pct"] = round(
                    deviation * annualizer * 100.0, 3
                )
        running_peak = window.cummax()
        drawdown = (window / running_peak - 1.0).min()
        if np.isfinite(drawdown):
            out["Max_Drawdown_1Y_Pct"] = round(float(drawdown) * 100.0, 3)
        absolute = returns.abs()
        total = float(absolute.sum())
        if total > 0:
            top = float(absolute.nlargest(min(5, len(absolute))).sum())
            out["Return_Concentration_1Y"] = round(top / total, 4)

    if opens is not None:
        open_values = pd.to_numeric(pd.Series(opens), errors="coerce")
        aligned = pd.DataFrame({"open": open_values, "close": values}).dropna()
        if len(aligned) >= 60:
            gaps = (
                aligned["open"] / aligned["close"].shift(1) - 1.0
            ).dropna().abs()
            gaps = gaps.iloc[-sessions_per_year:]
            if len(gaps) >= 60:
                out["Gap_Risk_Pct"] = round(
                    float(gaps.quantile(0.99)) * 100.0, 3
                )

    # --- trend smoothness ---------------------------------------------------
    # Signed R-squared of log price against time, on [-1, 1]. A steady advance
    # and a violent round-trip can share the same total return; the R-squared
    # part separates them. The sign matters just as much: an unsigned R-squared
    # scores a smooth, relentless DECLINE a perfect 1.0, and this feeds a
    # momentum block where higher is better. Carrying the slope's sign makes a
    # clean downtrend the worst reading rather than the best.
    trend_window = values.iloc[-126:]
    if len(trend_window) >= 100:
        y = np.log(trend_window.to_numpy(dtype=float))
        x = np.arange(len(y), dtype=float)
        if np.isfinite(y).all() and y.std() > 0:
            correlation = float(np.corrcoef(x, y)[0, 1])
            if np.isfinite(correlation):
                out["Trend_Quality_R2"] = round(
                    correlation**2 * np.sign(correlation), 4
                )
    return out

# =====================================================
# PRICE CACHE
# =====================================================
class PriceCache:
    # Columns that must exist in the cache schema. If a cache file predates one
    # of these (e.g. was written before Avg_Turnover_INR was added), every row
    # in it is missing that data and any filter relying on it would silently
    # drop everything - so treat such a cache as stale and force a refresh.
    REQUIRED_COLUMNS = (
        "Technical_Price",
        "Avg_Turnover_INR", "Median_Turnover_20D_INR",
        "Turnover_P10_20D_INR", "Median_Turnover_60D_INR",
        "Turnover_Top5_Share_60D", "Trading_Frequency_60D", "CMF_21",
        "Price_Return_20D_Pct", "Demand_Proxy_Status", "MA50_Slope_Pct",
        "ADX_Plus_DI", "ADX_Minus_DI",
        "Technical_Indicator_Version",
        "Price_Bar_As_Of", "Expected_Price_Bar_As_Of", "Price_Bar_Session_Lag",
        "Price_Bar_Complete", "Price_Session_Status", "Analysis_As_Of",
        "Price_Fetched_At",
    )
    # Required only for the Model 5.0/two-year cache contract. These columns
    # cannot be required from a 4.x v6 row without invalidating the production
    # cache even though the master factor switch is disabled.
    FACTOR_REQUIRED_COLUMNS = (
        "MA200", "MA200_Slope_Pct", "Price_To_MA200_Pct", "MA50_To_MA200_Pct",
        "Sessions_Above_MA200_Share", "Below_MA200_Streak",
        "Momentum_12_1_Pct", "Momentum_6_1_Pct", "Pct_Change_12M",
        "Volatility_Ann_Pct", "Downside_Deviation_Pct", "Max_Drawdown_1Y_Pct",
        "Gap_Risk_Pct", "Return_Concentration_1Y", "Trend_Quality_R2",
        "Price_History_Sessions",
    )

    @staticmethod
    def save(cache_path, records):
        try:
            pd.DataFrame(records).to_csv(cache_path, index=False)
        except Exception as e:
            logger.warning(f"Price cache save failed: {e}")

    @staticmethod
    def load(
        cache_path,
        max_age_hours=18,
        *,
        factor_model_enabled=False,
        allow_prior_session=False,
        as_of=None,
        completion_cutoff="16:15",
        market_timezone="Asia/Kolkata",
        market_holidays=(),
    ):
        """Return a schema-valid cache for the expected exchange session.

        Completed daily bars are immutable, so wall-clock age must not expire a
        Friday snapshot during a weekend/holiday (or before Monday's close).
        The cache is current when its recorded *expected session* matches the
        session the run is analysing.  Individual rows may carry an older bar;
        those rows remain explicit stale evidence and are policy-capped rather
        than invalidating and rebuilding the whole cross-section.

        ``allow_prior_session`` is used only as a per-symbol failure fallback
        while collecting a genuinely newer session.  It still enforces the
        schema, indicator version and provenance contract.
        """
        try:
            p = Path(cache_path)
            if not p.exists():
                return pd.DataFrame()
            timezone_info = (
                market_timezone
                if isinstance(market_timezone, ZoneInfo)
                else ZoneInfo(str(market_timezone))
            )
            current = pd.Timestamp(
                as_of if as_of is not None else datetime.now(timezone.utc)
            )
            if current.tzinfo is None:
                current = current.tz_localize(timezone_info)
            else:
                current = current.tz_convert(timezone_info)
            df = pd.read_csv(p)
            required_columns = PriceCache.REQUIRED_COLUMNS + (
                PriceCache.FACTOR_REQUIRED_COLUMNS
                if factor_model_enabled
                else ()
            )
            missing_columns = [c for c in required_columns if c not in df.columns]
            if missing_columns and not df.empty:
                logger.info(
                    f"Price cache is missing columns {missing_columns} - "
                    "ignoring and forcing a one-off full refresh."
                )
                return pd.DataFrame()
            expected_version = (
                TechnicalEnhancer.FACTOR_INDICATOR_VERSION
                if factor_model_enabled
                else TechnicalEnhancer.INDICATOR_VERSION
            )
            versions = pd.to_numeric(df["Technical_Indicator_Version"], errors="coerce")
            if versions.isna().any() or not versions.eq(expected_version).all():
                logger.info(
                    "Price cache uses a different technical-indicator contract - refreshing"
                )
                return pd.DataFrame()

            complete = df["Price_Bar_Complete"].map(
                lambda value: value is True
                or (isinstance(value, (int, float)) and value == 1)
                or str(value).strip().lower() in {"true", "1", "yes"}
            )
            bar_dates = pd.to_datetime(df["Price_Bar_As_Of"], errors="coerce").dt.date
            expected_dates = pd.to_datetime(
                df["Expected_Price_Bar_As_Of"], errors="coerce"
            ).dt.date
            fetched_at = pd.to_datetime(
                df["Price_Fetched_At"], errors="coerce", utc=True
            )
            analysis_at = pd.to_datetime(
                df["Analysis_As_Of"], errors="coerce", utc=True
            )
            if (
                bar_dates.isna().any()
                or expected_dates.isna().any()
                or fetched_at.isna().any()
                or analysis_at.isna().any()
            ):
                logger.info("Price cache has incomplete or invalid provenance - refreshing")
                return pd.DataFrame()

            if hasattr(completion_cutoff, "hour") and hasattr(completion_cutoff, "minute"):
                cutoff_time = completion_cutoff
            else:
                cutoff_time = None
                for pattern in ("%H:%M", "%H:%M:%S"):
                    try:
                        cutoff_time = datetime.strptime(
                            str(completion_cutoff).strip(), pattern
                        ).time()
                        break
                    except ValueError:
                        continue
                if cutoff_time is None:
                    raise ValueError(f"Invalid completion cutoff: {completion_cutoff!r}")

            today = current.date()
            current_time = current.time().replace(tzinfo=None)
            today_is_session = is_expected_nse_session(today, market_holidays)
            expected_session = latest_expected_completed_nse_session(
                today, current_time, cutoff_time, market_holidays
            )
            if (bar_dates > expected_dates).any() or (expected_dates > today).any():
                logger.info("Price cache contains impossible future provenance - refreshing")
                return pd.DataFrame()
            aligned_to_recorded_session = pd.Series(bar_dates).eq(expected_dates)
            if ((~complete) & aligned_to_recorded_session).any():
                logger.info(
                    "Price cache marks an expected-session bar incomplete - refreshing"
                )
                return pd.DataFrame()
            expected_matches = pd.Series(expected_dates).eq(expected_session)
            if not expected_matches.all():
                if allow_prior_session and pd.Series(expected_dates).le(
                    expected_session
                ).all():
                    return df
                logger.info(
                    "Price cache is not aligned to expected completed NSE session %s - refreshing",
                    expected_session,
                )
                return pd.DataFrame()

            if not today_is_session:
                # NSE has no regular daily bar on weekends; use the latest prior
                # completed session on weekends/configured holidays, subject to
                # the configured maximum age.
                if (expected_dates >= today).any():
                    logger.info(
                        "Price cache contains a same-day non-session bar - refreshing"
                    )
                    return pd.DataFrame()
            elif current_time < cutoff_time:
                if (expected_dates >= today).any():
                    logger.info(
                        "Price cache contains today's still-incomplete NSE daily bar - refreshing"
                    )
                    return pd.DataFrame()
            else:
                cutoff_at = pd.Timestamp(
                    datetime.combine(today, cutoff_time), tz=timezone_info
                ).tz_convert("UTC")
                if (fetched_at < cutoff_at).any() or (analysis_at < cutoff_at).any():
                    logger.info(
                        "Price cache snapshot predates today's completed-session "
                        "cutoff - refreshing"
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
    def __init__(self, output_dir, model_version=None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.output_dir / "backtest_history.csv"
        self.model_version = str(model_version or getattr(Config, "MODEL_VERSION", "unknown"))

    def log_run(self, date_str, scored_df):
        try:
            snapshot = scored_df[
                ["Symbol", "Current_Price", "Rating", "Combined_Score",
                 "Fundamental_Score", "Technical_Score"]
            ].copy()
            if "Final_Score" in scored_df:
                snapshot["Final_Score"] = scored_df["Final_Score"]
            snapshot["Model_Version"] = scored_df.get(
                "Model_Version",
                pd.Series(self.model_version, index=scored_df.index),
            ).astype(str)
            for column in (
                "Investment_Rating",
                "Portfolio_Actionable",
                "Liquidity_Grade",
                "NSE_Impact_Cost_Pct",
                "Demand_Proxy_Status",
            ):
                if column in scored_df:
                    snapshot[column] = scored_df[column]
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
            if "Model_Version" in realized:
                realized = realized[
                    realized["Model_Version"].astype(str).eq(self.model_version)
                ]
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
