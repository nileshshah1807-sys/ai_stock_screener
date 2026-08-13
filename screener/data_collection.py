"""NSE universe, price history, and fundamentals collection."""

import io
import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

from .market_data import (
    PriceCache,
    TechnicalEnhancer,
    calculate_trend_risk_features,
    expected_sessions_behind,
    is_expected_nse_session,
    latest_expected_completed_nse_session,
    normalize_market_holidays,
)

logger = logging.getLogger(__name__)


def _setting_enabled(value):
    """Interpret config booleans without treating the string ``"false"`` as true."""
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def calculate_liquidity_metrics(price_data, window_sessions=None):
    """Return execution and price-volume proxies from the existing OHLCV frame.

    Zero-volume sessions are deliberately retained. Dropping them makes an
    intermittently traded security appear more liquid than it is. ``CMF_21``
    with the 20-session return is a scored technical price-volume confirmation;
    it is not proof of institutional buying or selling.

    When ``window_sessions`` is provided, ``Avg_Turnover_INR`` is pinned to
    that trailing window. The default intentionally remains the whole supplied
    frame: that is the 4.x contract when Yahoo is asked for ``period="6mo"``.
    Model 5.0 passes 126 explicitly so its two-year download cannot redefine a
    six-month liquidity input.
    """
    columns = {}
    for name in ("High", "Low", "Close", "Volume"):
        source = price_data.get(name)
        if source is None:
            source = pd.Series(index=price_data.index, dtype=float)
        columns[name] = pd.to_numeric(source, errors="coerce")
    paired = pd.DataFrame(columns).dropna(subset=["Close", "Volume"])
    paired = paired[(paired["Close"] > 0) & (paired["Volume"] >= 0)]
    if paired.empty:
        return {}
    turnover = paired["Close"] * paired["Volume"]
    legacy_window = turnover.tail(int(window_sessions)) if window_sessions else turnover
    last_20 = turnover.tail(20)
    last_60 = turnover.tail(60)
    top_count = min(5, len(last_60))
    total_60 = float(last_60.sum())
    recent_60 = paired.tail(60)
    trading_frequency = float(recent_60["Volume"].gt(0).mean())

    # Actual turnover uses the unadjusted exchange close. Price signals use
    # Yahoo's adjusted close and consistently scaled high/low when available,
    # so a split does not masquerade as distribution or a large negative return.
    adjusted_close = pd.to_numeric(price_data.get("Adj Close"), errors="coerce") \
        if price_data.get("Adj Close") is not None else paired["Close"]
    adjustment_factor = adjusted_close / columns["Close"].where(columns["Close"].ne(0))
    signal_prices = pd.DataFrame({
        "High": columns["High"] * adjustment_factor,
        "Low": columns["Low"] * adjustment_factor,
        "Close": adjusted_close,
        "Volume": columns["Volume"],
    }).dropna(subset=["Close", "Volume"])
    signal_prices = signal_prices[
        (signal_prices["Close"] > 0) & (signal_prices["Volume"] >= 0)
    ]

    recent_21 = signal_prices.dropna(subset=["High", "Low"]).tail(21)
    cmf_21 = None
    if len(recent_21) >= 21:
        price_range = recent_21["High"] - recent_21["Low"]
        money_flow_multiplier = (
            (2.0 * recent_21["Close"] - recent_21["High"] - recent_21["Low"])
            / price_range.where(price_range.ne(0))
        ).fillna(0.0)
        volume_sum = float(recent_21["Volume"].sum())
        if volume_sum > 0:
            cmf_21 = float((money_flow_multiplier * recent_21["Volume"]).sum() / volume_sum)

    recent_close = signal_prices["Close"].tail(21)
    return_20d = None
    if len(recent_close) >= 21 and float(recent_close.iloc[0]) > 0:
        return_20d = (float(recent_close.iloc[-1]) / float(recent_close.iloc[0]) - 1.0) * 100.0

    if cmf_21 is None or return_20d is None:
        demand_proxy = "Unavailable"
    elif cmf_21 > 0 and return_20d > 0:
        demand_proxy = "Accumulation proxy"
    elif cmf_21 < 0 and return_20d < 0:
        demand_proxy = "Distribution proxy"
    else:
        demand_proxy = "Mixed"

    return {
        "Avg_Turnover_INR": float(legacy_window.mean()),
        "Median_Turnover_20D_INR": float(last_20.median()),
        "Turnover_P10_20D_INR": float(last_20.quantile(0.10)),
        "Median_Turnover_60D_INR": float(last_60.median()),
        "Turnover_Top5_Share_60D": (
            float(last_60.nlargest(top_count).sum()) / total_60
            if total_60 > 0 else 1.0
        ),
        "Turnover_Observations": int(len(turnover)),
        "Trading_Frequency_60D": trading_frequency,
        "CMF_21": cmf_21,
        "Price_Return_20D_Pct": return_20d,
        "Demand_Proxy_Status": demand_proxy,
        "Demand_Proxy_Method": (
            "21D CMF plus 20-session adjusted-price return; scored technical "
            "confirmation, not institutional-flow proof"
        ),
    }


def align_valuation_to_completed_price_bar(merged_df):
    """Align price-dependent valuation fields to ``Current_Price``.

    Yahoo quote metadata and the completed daily close can be observed at
    different times. This helper preserves the fetched values for audit, then
    recomputes each metric only when all required raw inputs are available.
    Call it immediately after merging technical and fundamental frames.
    """
    frame = merged_df.copy()
    if frame.empty:
        return frame

    def numeric(column):
        return pd.to_numeric(
            frame.get(column, pd.Series(index=frame.index, dtype=float)),
            errors="coerce",
        )

    source_columns = {
        "PE_Ratio": "PE_Ratio_As_Fetched",
        "PB_Ratio": "PB_Ratio_As_Fetched",
        "Market_Cap": "Market_Cap_As_Fetched",
        "EV_EBITDA": "EV_EBITDA_As_Fetched",
        "Dividend_Yield": "Dividend_Yield_As_Fetched",
        "Dividend_Yield_Ratio": "Dividend_Yield_Ratio_As_Fetched",
    }
    for metric, audit_column in source_columns.items():
        if audit_column not in frame.columns:
            frame[audit_column] = numeric(metric)

    price = numeric("Current_Price")
    eps = numeric("EPS")
    book_value = numeric("Book_Value")
    shares = numeric("Shares_Outstanding")
    ebitda = numeric("EBITDA")
    debt = numeric("Total_Debt")
    cash = numeric("Total_Cash")
    dividend_rate = numeric("Dividend_Rate")
    fetched_dividend_ratio = numeric("Dividend_Yield_Ratio_As_Fetched")
    fetched_dividend_ratio = fetched_dividend_ratio.where(
        fetched_dividend_ratio.notna(), numeric("Dividend_Yield_As_Fetched") / 100.0
    )

    pe_valid = price.gt(0) & eps.notna() & eps.ne(0)
    pb_valid = price.gt(0) & book_value.notna() & book_value.ne(0)
    market_cap_valid = price.gt(0) & shares.gt(0)
    recomputed_market_cap = price * shares
    ev_valid = (
        market_cap_valid
        & debt.notna()
        & cash.notna()
        & ebitda.notna()
        & ebitda.ne(0)
    )
    fetched_price = numeric("Market_Cap_As_Fetched") / shares
    derived_dividend_rate = fetched_dividend_ratio * fetched_price
    dividend_rate_used = dividend_rate.where(
        dividend_rate.notna(), derived_dividend_rate
    )
    dividend_valid = price.gt(0) & dividend_rate_used.notna() & dividend_rate_used.ge(0)

    frame["PE_Ratio"] = (price / eps).where(pe_valid, numeric("PE_Ratio"))
    frame["PB_Ratio"] = (price / book_value).where(pb_valid, numeric("PB_Ratio"))
    frame["Market_Cap"] = recomputed_market_cap.where(
        market_cap_valid, numeric("Market_Cap")
    )
    enterprise_value = recomputed_market_cap + debt - cash
    frame["EV_EBITDA"] = (enterprise_value / ebitda).where(
        ev_valid, numeric("EV_EBITDA")
    )
    aligned_dividend_ratio = dividend_rate_used / price
    # An unaligned cached yield is excluded from scoring; its fetched value is
    # retained in the *_As_Fetched columns. Most legacy rows can be aligned by
    # deriving annual dividend/share from fetched yield and fetched price.
    frame["Dividend_Yield_Ratio"] = aligned_dividend_ratio.where(dividend_valid)
    frame["Dividend_Yield"] = (aligned_dividend_ratio * 100.0).where(dividend_valid)

    frame["PE_Ratio_Price_Aligned"] = pe_valid
    frame["PB_Ratio_Price_Aligned"] = pb_valid
    frame["Market_Cap_Price_Aligned"] = market_cap_valid
    frame["EV_EBITDA_Price_Aligned"] = ev_valid
    frame["Dividend_Yield_Price_Aligned"] = dividend_valid
    frame["Dividend_Rate_Alignment_Source"] = "unavailable"
    frame.loc[dividend_valid & dividend_rate.notna(), "Dividend_Rate_Alignment_Source"] = (
        "reported_dividend_rate"
    )
    frame.loc[
        dividend_valid & dividend_rate.isna() & derived_dividend_rate.notna(),
        "Dividend_Rate_Alignment_Source",
    ] = "derived_from_fetched_yield_and_price"
    aligned_count = pd.concat(
        [pe_valid, pb_valid, market_cap_valid, ev_valid, dividend_valid], axis=1
    ).sum(axis=1)
    frame["Valuation_Price_Alignment_Status"] = "partial"
    frame.loc[aligned_count.eq(5), "Valuation_Price_Alignment_Status"] = "complete"
    frame.loc[aligned_count.eq(0), "Valuation_Price_Alignment_Status"] = "unavailable"
    frame["Valuation_Price_As_Of"] = frame.get(
        "Price_Bar_As_Of", pd.Series(index=frame.index, dtype="object")
    )
    frame["Valuation_Alignment_Method"] = (
        "Completed close with raw EPS/book value/shares/EBITDA/debt/cash; "
        "fetched value retained where raw inputs are unavailable"
    )
    return frame


class StockDataCollector:
    # key fundamental fields used by the data-completeness gate (P2)
    FUND_KEY_FIELDS = ("PE_Ratio", "ROE", "Profit_Margin", "Revenue_Growth")
    DEFAULT_MARKET_TIMEZONE = "Asia/Kolkata"
    # NSE permits trade modifications through 16:15. A daily observation is
    # therefore not treated as final until that exchange deadline has passed.
    DEFAULT_PRICE_BAR_COMPLETION_CUTOFF = "16:15"

    def __init__(
        self,
        config,
        *,
        clock=None,
        completion_cutoff=None,
        market_timezone=None,
    ):
        self.config = config
        self.collection_diagnostics = {
            "schema_version": 1,
            "universe_source_url": (
                "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
            ),
            "universe_fetch_status": "not_started",
            "universe_source_sha256": None,
            "universe_source_symbol_count": 0,
            "universe_selected_symbols": [],
            "technical_requested_symbols": [],
            "technical_collected_symbols": [],
            "technical_failed_symbols": [],
            "fundamental_requested_symbols": [],
            "fundamental_fetch_requested_symbols": [],
            "fundamental_collected_symbols": [],
            "fundamental_missing_symbols": [],
        }
        timezone_name = (
            market_timezone
            or getattr(config, "ANALYSIS_TIMEZONE", None)
            or getattr(config, "NSE_MARKET_TIMEZONE", None)
            or os.getenv("NSE_MARKET_TIMEZONE")
            or self.DEFAULT_MARKET_TIMEZONE
        )
        self.market_timezone = ZoneInfo(str(timezone_name))
        cutoff_value = (
            completion_cutoff
            or getattr(config, "MARKET_BAR_COMPLETE_AFTER_IST", None)
            or getattr(config, "NSE_PRICE_BAR_COMPLETION_CUTOFF", None)
            or os.getenv("MARKET_BAR_COMPLETE_AFTER_IST")
            or os.getenv("NSE_PRICE_BAR_COMPLETION_CUTOFF")
            or self.DEFAULT_PRICE_BAR_COMPLETION_CUTOFF
        )
        try:
            self.price_bar_completion_cutoff = self._parse_completion_cutoff(cutoff_value)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid NSE price-bar completion cutoff %r; using %s",
                cutoff_value,
                self.DEFAULT_PRICE_BAR_COMPLETION_CUTOFF,
            )
            self.price_bar_completion_cutoff = self._parse_completion_cutoff(
                self.DEFAULT_PRICE_BAR_COMPLETION_CUTOFF
            )
        # A clock callable makes the session boundary deterministic in tests.
        # Naive injected datetimes are interpreted as local exchange time.
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.allow_provisional_market_bars = bool(
            getattr(config, "ALLOW_PROVISIONAL_MARKET_BARS", False)
        )
        self.market_holidays = normalize_market_holidays(
            getattr(config, "NSE_MARKET_HOLIDAYS", ())
        )
        self.collection_diagnostics["market_calendar_version"] = getattr(
            config, "NSE_MARKET_CALENDAR_VERSION", "unconfigured"
        )
        self.collection_diagnostics["market_holidays"] = sorted(
            day.isoformat() for day in self.market_holidays
        )

    @staticmethod
    def _parse_completion_cutoff(value):
        if hasattr(value, "hour") and hasattr(value, "minute"):
            return value
        text = str(value).strip()
        for pattern in ("%H:%M", "%H:%M:%S"):
            try:
                return datetime.strptime(text, pattern).time()
            except ValueError:
                continue
        raise ValueError(f"Invalid completion cutoff: {value!r}")

    def _now_market(self):
        current = pd.Timestamp(self._clock())
        if current.tzinfo is None:
            current = current.tz_localize(self.market_timezone)
        else:
            current = current.tz_convert(self.market_timezone)
        return current

    @staticmethod
    def _market_bar_dates(index, market_timezone):
        """Return exchange-local dates for a daily-price index, or ``None``.

        Yahoo daily frames use a DatetimeIndex. Numeric indexes are deliberately
        not interpreted as nanoseconds since 1970: without a date, completion
        cannot be proved and the output is marked accordingly.
        """
        if isinstance(index, pd.DatetimeIndex):
            parsed = index
        elif getattr(index, "dtype", None) is not None and not pd.api.types.is_numeric_dtype(
            index.dtype
        ):
            parsed = pd.DatetimeIndex(pd.to_datetime(index, errors="coerce"))
        else:
            return None
        if len(parsed) == 0 or parsed.isna().all():
            return None
        if parsed.tz is not None:
            parsed = parsed.tz_convert(market_timezone)
        return [timestamp.date() if not pd.isna(timestamp) else None for timestamp in parsed]

    def _select_completed_price_bars(self, price_data, analysis_as_of):
        """Select only daily bars complete at ``analysis_as_of``.

        The same selected frame is subsequently used for current price,
        indicators, returns, volume and liquidity. Older bars are complete;
        today's bar becomes complete only at/after the configured NSE cutoff.
        """
        bar_dates = self._market_bar_dates(price_data.index, self.market_timezone)
        if bar_dates is None:
            return price_data.copy(), None, False

        today = analysis_as_of.date()
        current_time = analysis_as_of.time().replace(tzinfo=None)
        today_complete = current_time >= self.price_bar_completion_cutoff
        today_is_session = is_expected_nse_session(today, self.market_holidays)
        expected_session = latest_expected_completed_nse_session(
            today,
            current_time,
            self.price_bar_completion_cutoff,
            self.market_holidays,
        )
        selected_positions = [
            position
            for position, bar_date in enumerate(bar_dates)
            if bar_date is not None
            and (
                bar_date < today
                or (
                    bar_date == today
                    and (today_complete or self.allow_provisional_market_bars)
                )
            )
        ]
        if not selected_positions:
            return price_data.iloc[0:0].copy(), None, False

        # A daily provider normally returns ascending rows, but sorting here
        # prevents the current price and rolling indicators selecting different
        # observations when a provider response arrives out of order.
        selected_positions.sort(key=lambda position: bar_dates[position])
        selected = price_data.iloc[selected_positions].copy()
        latest_date = bar_dates[selected_positions[-1]]
        if latest_date != expected_session:
            # A symbol lagging the cross-section (suspension/vendor delay) is
            # data-limited, even if its last observation is historically final.
            return price_data.iloc[0:0].copy(), latest_date, False
        latest_complete = latest_date < today or (
            latest_date == today and today_complete
        )
        return selected, latest_date, latest_complete

    def get_comprehensive_stock_list(self):
        logger.info("Fetching comprehensive NSE stock list...")
        all_symbols = set()
        try:
            url = self.collection_diagnostics["universe_source_url"]
            resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                self.collection_diagnostics["universe_fetch_status"] = "ok"
                self.collection_diagnostics["universe_fetched_at"] = (
                    self._now_market().to_pydatetime().isoformat(timespec="seconds")
                )
                self.collection_diagnostics["universe_source_sha256"] = (
                    hashlib.sha256(resp.content).hexdigest()
                )
                df = pd.read_csv(io.StringIO(resp.text))
                all_symbols.update(df["SYMBOL"].dropna().str.strip().tolist())
                self.collection_diagnostics["universe_source_symbol_count"] = len(
                    all_symbols
                )
                logger.info(f"NSE Master: {len(all_symbols)} symbols")
            else:
                self.collection_diagnostics["universe_fetch_status"] = (
                    f"http_{resp.status_code}"
                )
                logger.error(
                    f"NSE master list returned HTTP {resp.status_code} - "
                    "falling back to built-in watchlist only!"
                )
        except Exception as e:
            self.collection_diagnostics["universe_fetch_status"] = (
                f"error:{type(e).__name__}"
            )
            logger.error(f"NSE Master fetch failed ({e}) - falling back to built-in watchlist only!")

        # Well-known liquid names as a safety net
        additional_stocks = [
            "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "ITC",
            "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT",
            "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO", "BAJFINANCE", "HCLTECH",
            "WIPRO", "NESTLEIND", "POWERGRID", "NTPC", "M&M", "TMCV", "ONGC",
            "JSWSTEEL", "TATASTEEL", "ADANIENT", "COALINDIA", "DRREDDY", "CIPLA",
            "DIVISLAB", "TECHM", "GRASIM", "BRITANNIA", "EICHERMOT", "APOLLOHOSP",
            "HEROMOTOCO", "UPL", "BANKBARODA", "LICI", "ETERNAL", "DELHIVERY",
            "HUDCO", "IREDA",
        ]
        all_symbols.update(additional_stocks)
        filtered = {
            str(s).strip().upper()
            for s in all_symbols
            if s and len(str(s)) <= 20
        }
        if not self.config.SCAN_ALL_NSE:
            filtered = {s.upper() for s in self.config.CUSTOM_WATCHLIST}
            self.collection_diagnostics["universe_fetch_status"] += (
                ":custom_watchlist_override"
            )
        self.collection_diagnostics["universe_selected_symbols"] = sorted(filtered)
        logger.info(f"Total symbols to scan: {len(filtered)}")
        return sorted(filtered)

    def download_stock_data(self, symbols):
        logger.info(f"Technical download for {len(symbols)} stocks...")
        requested_symbols = sorted({str(symbol).strip().upper() for symbol in symbols})
        self.collection_diagnostics["technical_requested_symbols"] = requested_symbols
        results = []
        failed = []
        factor_model_enabled = _setting_enabled(
            getattr(self.config, "FACTOR_MODEL_ENABLED", False)
        )
        analysis_as_of = self._now_market()
        analysis_as_of_text = analysis_as_of.to_pydatetime().isoformat(timespec="seconds")
        expected_price_session = latest_expected_completed_nse_session(
            analysis_as_of.date(),
            analysis_as_of.time().replace(tzinfo=None),
            self.price_bar_completion_cutoff,
            self.market_holidays,
        )

        # --- Feature: price cache reuse ---
        cache_path = self.config.OUTPUT_DIR / "price_cache.csv"
        cached = PriceCache.load(
            cache_path,
            self.config.PRICE_CACHE_MAX_AGE_HOURS,
            factor_model_enabled=factor_model_enabled,
            as_of=analysis_as_of,
            completion_cutoff=self.price_bar_completion_cutoff,
            market_timezone=self.market_timezone,
            market_holidays=self.market_holidays,
        )
        cached_records = []
        to_download = list(symbols)
        if not cached.empty and "Symbol" in cached.columns:
            cached = cached.copy()
            cached["Analysis_As_Of"] = analysis_as_of_text
            cached["Expected_Price_Bar_As_Of"] = expected_price_session.isoformat()
            # PriceCache.load only returns rows already equal to the expected
            # session, so anything surviving here is aligned by construction.
            cached["Price_Bar_Session_Lag"] = 0
            cached["Price_Bar_Aligned"] = True
            cached["Price_Session_Status"] = (
                "current_completed_session"
                if expected_price_session == analysis_as_of.date()
                else "prior_completed_non_session"
            )
            cached_symbols = set(cached["Symbol"].astype(str))
            cached_records = cached[cached["Symbol"].isin(symbols)].to_dict("records")
            to_download = [s for s in symbols if s not in cached_symbols]
            logger.info(
                f"Price cache hit: {len(cached_records)} reused, {len(to_download)} to download"
            )

        # Preserve the production 4.x data contract exactly while Model 5.0 is
        # disabled. In particular, Yahoo's ``6mo`` is a calendar period and is
        # not guaranteed to contain exactly 126 rows, so downloading two years
        # and truncating to 126 would still change legacy scores. The factor
        # path opts into the longer history and pins explicitly six-month
        # features to ``legacy_window`` below.
        history_period = (
            str(getattr(self.config, "PRICE_HISTORY_PERIOD", "2y") or "2y")
            if factor_model_enabled
            else "6mo"
        )
        legacy_window = (
            int(getattr(self.config, "LEGACY_HISTORY_WINDOW_SESSIONS", 126) or 126)
            if factor_model_enabled
            else None
        )
        min_sessions = (
            int(getattr(self.config, "MIN_PRICE_SESSIONS_REQUIRED", 60) or 60)
            if factor_model_enabled
            else 60
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
                    " ".join(batch), period=history_period, group_by="ticker",
                    progress=False, threads=True, auto_adjust=False,
                )
                fetched_at_text = self._now_market().to_pydatetime().isoformat(timespec="seconds")
                for symbol in batch:
                    clean_sym = symbol.replace(".NS", "")
                    try:
                        if isinstance(data.columns, pd.MultiIndex):
                            if symbol not in data.columns.get_level_values(0):
                                failed.append(clean_sym)
                                continue
                            price_data = data[symbol]
                        else:
                            price_data = data
                        if price_data is None or price_data.empty:
                            failed.append(clean_sym)
                            continue
                        price_data, price_bar_as_of, price_bar_complete = (
                            self._select_completed_price_bars(price_data, analysis_as_of)
                        )
                        if price_data.empty:
                            failed.append(clean_sym)
                            continue
                        raw_close_aligned = pd.to_numeric(price_data["Close"], errors="coerce")
                        adjusted_close_aligned = pd.to_numeric(
                            price_data.get("Adj Close", price_data["Close"]), errors="coerce"
                        )
                        volume_aligned = pd.to_numeric(price_data["Volume"], errors="coerce")
                        usable_rows = (
                            raw_close_aligned.notna()
                            & adjusted_close_aligned.notna()
                            & volume_aligned.notna()
                        )
                        price_data = price_data.loc[usable_rows].copy()
                        if price_data.empty:
                            failed.append(clean_sym)
                            continue
                        raw_closes = raw_close_aligned.loc[usable_rows]
                        closes = adjusted_close_aligned.loc[usable_rows]
                        volumes = volume_aligned.loc[usable_rows]
                        usable_bar_dates = self._market_bar_dates(
                            price_data.index, self.market_timezone
                        )
                        if usable_bar_dates is not None and usable_bar_dates[-1] is not None:
                            price_bar_as_of = usable_bar_dates[-1]
                            # The usable-rows filter above can drop the expected
                            # session itself when the vendor leaves a NaN close
                            # or volume on it. Alignment was checked before that
                            # filter, so it has to be re-established here: being
                            # older than today does NOT make a bar the completed
                            # session the cross-section is measured on.
                            price_bar_complete = (
                                price_bar_as_of == expected_price_session
                                and (
                                    price_bar_as_of < analysis_as_of.date()
                                    or (
                                        price_bar_as_of == analysis_as_of.date()
                                        and analysis_as_of.time().replace(tzinfo=None)
                                        >= self.price_bar_completion_cutoff
                                    )
                                )
                            )
                        if (
                            len(closes) < min_sessions
                            or len(raw_closes) < min_sessions
                            or len(volumes) == 0
                        ):
                            failed.append(clean_sym)
                            continue
                        current_price = float(raw_closes.iloc[-1])
                        signal_current_price = float(closes.iloc[-1])
                        # Model 5 pins this input inside its longer download.
                        # With the flag off, ``legacy_window`` is None and the
                        # whole Yahoo ``6mo`` response is used exactly as in 4.x.
                        volume_window = (
                            volumes.tail(legacy_window)
                            if legacy_window is not None
                            else volumes
                        )
                        avg_volume = float(volume_window.mean())
                        last_volume = float(volumes.iloc[-1])
                        liquidity = calculate_liquidity_metrics(
                            price_data, window_sessions=legacy_window
                        )
                        if (
                            avg_volume == 0
                            or pd.isna(avg_volume)
                            or last_volume == 0
                            or current_price <= 0
                            or not liquidity
                        ):
                            failed.append(clean_sym)
                            continue
                        ma20 = float(closes.rolling(20).mean().iloc[-1])
                        ma50_series = closes.rolling(50).mean()
                        ma50 = float(ma50_series.iloc[-1])
                        # MA50 slope (now vs ~20 trading days ago) - price sitting close to a
                        # still-FALLING MA50 is not the same as genuine strength, it just means
                        # price has caught up to a declining average. Used to adjust the MA50
                        # distance score in score_technical() instead of rewarding closeness blindly.
                        if len(ma50_series) >= 21 and pd.notna(ma50_series.iloc[-21]) and ma50_series.iloc[-21] != 0:
                            ma50_slope_pct = ((ma50 / float(ma50_series.iloc[-21])) - 1) * 100
                        else:
                            ma50_slope_pct = float("nan")
                        rsi_series = TechnicalEnhancer._rsi(closes, 14)
                        current_rsi = (
                            float(rsi_series.iloc[-1])
                            if not pd.isna(rsi_series.iloc[-1]) else float("nan")
                        )
                        ema12 = closes.ewm(span=12, adjust=False).mean()
                        ema26 = closes.ewm(span=26, adjust=False).mean()
                        macd = ema12 - ema26
                        signal = macd.ewm(span=9, adjust=False).mean()
                        bb_mid = closes.rolling(20).mean()
                        bb_std = closes.rolling(20).std()
                        bb_upper = bb_mid + 2 * bb_std
                        bb_lower = bb_mid - 2 * bb_std
                        bb_range = float(bb_upper.iloc[-1]) - float(bb_lower.iloc[-1])
                        bb_pos = (
                            (signal_current_price - float(bb_lower.iloc[-1])) / bb_range
                            if bb_range and bb_range > 0 else 0.5
                        )
                        pct_1m = TechnicalEnhancer.calculate_pct_return(closes, 21)
                        pct_3m = TechnicalEnhancer.calculate_pct_return(closes, 65)
                        pct_6m_lookback = (
                            legacy_window
                            if legacy_window is not None
                            else len(closes) - 1
                        )
                        pct_6m = TechnicalEnhancer.calculate_pct_return(
                            closes, pct_6m_lookback
                        )
                        vol_avg_20 = float(volumes.rolling(20).mean().iloc[-1])
                        vol_ratio = last_volume / vol_avg_20 if vol_avg_20 and vol_avg_20 > 0 else 1.0
                        raw_close_aligned = pd.to_numeric(price_data["Close"], errors="coerce")
                        adjustment_factor = pd.to_numeric(
                            price_data.get("Adj Close", price_data["Close"]), errors="coerce"
                        ) / raw_close_aligned.where(raw_close_aligned.ne(0))
                        high = pd.to_numeric(price_data["High"], errors="coerce") * adjustment_factor
                        low = pd.to_numeric(price_data["Low"], errors="coerce") * adjustment_factor
                        if factor_model_enabled:
                            adjusted_open = (
                                pd.to_numeric(price_data.get("Open"), errors="coerce")
                                * adjustment_factor
                                if price_data.get("Open") is not None
                                else None
                            )
                            trend_risk = calculate_trend_risk_features(
                                closes, opens=adjusted_open
                            )
                        else:
                            trend_risk = {}
                        directional_prices = pd.DataFrame({
                            "High": high,
                            "Low": low,
                            "Close": closes,
                        }).dropna()
                        high = directional_prices["High"]
                        low = directional_prices["Low"]
                        directional_closes = directional_prices["Close"]
                        adx_val, adx_plus_di, adx_minus_di = TechnicalEnhancer.calculate_adx(
                            high, low, directional_closes, 14
                        )
                        stoch_rsi_val = TechnicalEnhancer.calculate_stoch_rsi(closes, 14)
                        atr_val = TechnicalEnhancer.calculate_atr(
                            high, low, directional_closes, 14
                        )
                        results.append({
                            "Symbol": clean_sym,
                            "Current_Price": round(current_price, 2),
                            # All indicators are calculated on adjusted OHLC.
                            # Keep their price denominator on that same scale;
                            # raw close remains Current_Price for valuation,
                            # turnover and display.
                            "Technical_Price": round(signal_current_price, 2),
                            "Price_Bar_As_Of": (
                                price_bar_as_of.isoformat()
                                if price_bar_as_of is not None else None
                            ),
                            "Expected_Price_Bar_As_Of": expected_price_session.isoformat(),
                            # A real count, never null: a null lag reads as
                            # "unknown" and hid 64% of the 2026-08-11 universe
                            # sitting three sessions behind the cross-section.
                            "Price_Bar_Session_Lag": expected_sessions_behind(
                                price_bar_as_of,
                                expected_price_session,
                                self.market_holidays,
                            ),
                            "Price_Bar_Aligned": bool(
                                price_bar_as_of == expected_price_session
                            ),
                            "Price_Bar_Complete": bool(price_bar_complete),
                            "Price_Session_Status": (
                                "current_completed_session"
                                if price_bar_as_of == analysis_as_of.date()
                                and price_bar_complete
                                else "prior_completed_pending_session"
                                if price_bar_as_of is not None
                                and price_bar_as_of < analysis_as_of.date()
                                and is_expected_nse_session(
                                    analysis_as_of.date(), self.market_holidays
                                )
                                else "prior_completed_non_session"
                                if price_bar_as_of is not None
                                and price_bar_as_of < analysis_as_of.date()
                                else "provisional_current_session"
                            ),
                            "Analysis_As_Of": analysis_as_of_text,
                            "Price_Fetched_At": fetched_at_text,
                            "MA20": round(ma20, 2),
                            "MA50": round(ma50, 2),
                            "MA50_Slope_Pct": round(ma50_slope_pct, 2),
                            "RSI_14": round(current_rsi, 2),
                            "Technical_Indicator_Version": (
                                TechnicalEnhancer.FACTOR_INDICATOR_VERSION
                                if factor_model_enabled
                                else TechnicalEnhancer.INDICATOR_VERSION
                            ),
                            "MACD": round(float(macd.iloc[-1]), 4),
                            "MACD_Signal": round(float(signal.iloc[-1]), 4),
                            "ADX_14": round(adx_val, 2),
                            "ADX_Plus_DI": round(adx_plus_di, 2),
                            "ADX_Minus_DI": round(adx_minus_di, 2),
                            "StochRSI_14": round(stoch_rsi_val, 2),
                            "ATR_14": round(atr_val, 2),
                            "High_6M": round(
                                float(
                                    closes.tail(legacy_window).max()
                                    if legacy_window is not None
                                    else closes.max()
                                ),
                                2,
                            ),
                            "Low_6M": round(
                                float(
                                    closes.tail(legacy_window).min()
                                    if legacy_window is not None
                                    else closes.min()
                                ),
                                2,
                            ),
                            "Pct_Change_1M": round(pct_1m, 2),
                            "Pct_Change_3M": round(pct_3m, 2),
                            "Pct_Change_6M": round(pct_6m, 2),
                            **trend_risk,
                            "Avg_Volume": int(avg_volume),
                            "Avg_Turnover_INR": round(liquidity["Avg_Turnover_INR"], 2),
                            "Median_Turnover_20D_INR": round(
                                liquidity["Median_Turnover_20D_INR"], 2
                            ),
                            "Turnover_P10_20D_INR": round(
                                liquidity["Turnover_P10_20D_INR"], 2
                            ),
                            "Median_Turnover_60D_INR": round(
                                liquidity["Median_Turnover_60D_INR"], 2
                            ),
                            "Turnover_Top5_Share_60D": round(
                                liquidity["Turnover_Top5_Share_60D"], 4
                            ),
                            "Turnover_Observations": liquidity["Turnover_Observations"],
                            "Trading_Frequency_60D": round(
                                liquidity["Trading_Frequency_60D"], 4
                            ),
                            "CMF_21": (
                                round(liquidity["CMF_21"], 4)
                                if liquidity["CMF_21"] is not None else None
                            ),
                            "Price_Return_20D_Pct": (
                                round(liquidity["Price_Return_20D_Pct"], 2)
                                if liquidity["Price_Return_20D_Pct"] is not None else None
                            ),
                            "Demand_Proxy_Status": liquidity["Demand_Proxy_Status"],
                            "Demand_Proxy_Method": liquidity["Demand_Proxy_Method"],
                            "Vol_Ratio": round(vol_ratio, 2),
                            "BB_Position": round(bb_pos, 2),
                        })
                    except Exception:
                        failed.append(clean_sym)
            except Exception as e:
                logger.error(f"Batch {batch_num} error: {e}")
                continue

        all_records = cached_records + results
        collected_symbols = sorted(
            {
                str(record.get("Symbol", "")).strip().upper()
                for record in all_records
                if str(record.get("Symbol", "")).strip()
            }
        )
        self.collection_diagnostics["technical_collected_symbols"] = collected_symbols
        self.collection_diagnostics["technical_failed_symbols"] = sorted(
            set(requested_symbols) - set(collected_symbols)
        )
        self.collection_diagnostics["technical_cached_symbols"] = sorted(
            {
                str(record.get("Symbol", "")).strip().upper()
                for record in cached_records
                if str(record.get("Symbol", "")).strip()
            }
        )
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
    REQUIRED_FUND_COLUMNS = (
        "Company", "Sector", "Industry", "EPS", "Book_Value",
        "Shares_Outstanding", "EBITDA", "Total_Debt", "Total_Cash",
        "Dividend_Rate",
        "Fundamental_Fetched_At", "Fundamental_Source",
    )

    @staticmethod
    def _prepare_fundamental_frame(records):
        """Expose Yahoo's percentage yield and a ratio used by the scorer."""
        frame = pd.DataFrame(records)
        if frame.empty:
            return frame
        legacy_date = frame.get(
            "Cached_Date", pd.Series(index=frame.index, dtype="object")
        )
        fetched_at = frame.get(
            "Fundamental_Fetched_At", pd.Series(index=frame.index, dtype="object")
        )
        precise_timestamp = fetched_at.notna() & fetched_at.astype(str).str.strip().ne("")
        fetched_at = fetched_at.where(precise_timestamp, legacy_date)
        frame["Fundamental_Fetched_At"] = fetched_at
        fundamental_as_of = frame.get(
            "Fundamental_As_Of", pd.Series(index=frame.index, dtype="object")
        )
        frame["Fundamental_As_Of"] = fundamental_as_of.where(
            fundamental_as_of.notna() & fundamental_as_of.astype(str).str.strip().ne(""),
            fetched_at,
        )
        quality = pd.Series("fetch_timestamp", index=frame.index, dtype="object")
        quality.loc[~precise_timestamp] = "legacy_cache_date"
        frame["Fundamental_As_Of_Quality"] = frame.get(
            "Fundamental_As_Of_Quality", quality
        ).fillna(quality)
        source = frame.get(
            "Fundamental_Source", pd.Series(index=frame.index, dtype="object")
        )
        frame["Fundamental_Source"] = source.fillna("Yahoo Finance quote metadata")
        raw_yield = pd.to_numeric(
            frame.get("Dividend_Yield", pd.Series(index=frame.index, dtype=float)),
            errors="coerce",
        )
        # Current Yahoo quote metadata expresses dividendYield in percentage
        # points (TCS 2.74 means 2.74%), while all other profitability/growth
        # inputs in this model are ratios.  Preserve the raw field for auditing.
        frame["Dividend_Yield_Ratio"] = raw_yield / 100.0
        frame["Dividend_Yield_Source_Unit"] = "percent"
        return frame

    @staticmethod
    def _company_name(info, symbol):
        """Return a displayable company name from Yahoo's quote metadata.

        Yahoo's NSE quote payload is not completely uniform: most equities have
        ``longName``, while some only provide ``shortName`` or ``displayName``.
        A symbol is always a safer report fallback than a blank/NaN company
        cell, including when Yahoo temporarily omits all of these fields.
        """
        if not isinstance(info, dict):
            return str(symbol)
        for key in ("longName", "shortName", "displayName"):
            value = info.get(key)
            if value is not None and str(value).strip() and str(value).strip().lower() != "nan":
                return str(value).strip()
        return str(symbol)

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

        # A previous report version wrote an empty Company column.  Treat only
        # those otherwise-fresh rows as stale so the next run backfills their
        # Yahoo quote name instead of carrying NaN into another PDF.
        if "Company" in df.columns:
            company_values = df["Company"].fillna("").astype(str).str.strip().str.lower()
            fresh_mask &= company_values.ne("") & company_values.ne("nan")
        fresh_records = df[fresh_mask].to_dict("records")
        stale_symbols = set(df.loc[~fresh_mask, "Symbol"])
        return fresh_records, stale_symbols

    def _record_fundamental_diagnostics(self, frame, requested_symbols):
        collected = (
            set(frame["Symbol"].dropna().astype(str).str.strip().str.upper())
            if frame is not None and not frame.empty and "Symbol" in frame
            else set()
        )
        requested = {str(symbol).strip().upper() for symbol in requested_symbols}
        self.collection_diagnostics["fundamental_collected_symbols"] = sorted(
            collected
        )
        self.collection_diagnostics["fundamental_missing_symbols"] = sorted(
            requested - collected
        )

    def get_fundamental_data(self, tech_df):
        cache_file = self.config.OUTPUT_DIR / "fundamental_cache.csv"
        fresh_records, stale_symbols = [], set()
        cached_df = pd.DataFrame()
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
        self.collection_diagnostics["fundamental_requested_symbols"] = sorted(
            {str(symbol).strip().upper() for symbol in all_symbols}
        )
        fresh_symbols = {r["Symbol"] for r in fresh_records} & all_symbols
        needs_fetch = sorted(all_symbols - fresh_symbols)
        self.collection_diagnostics["fundamental_fetch_requested_symbols"] = [
            str(symbol).strip().upper() for symbol in needs_fetch
        ]
        logger.info(
            f"Fundamentals: {len(fresh_symbols)} fresh-cached, "
            f"{len(stale_symbols & all_symbols)} expired (> {self.config.FUND_CACHE_MAX_AGE_DAYS}d), "
            f"{len(needs_fetch)} to fetch"
        )
        fundamental_data = [
            {**r, "Fund_Data_Stale": False}
            for r in fresh_records if r["Symbol"] in all_symbols
        ]
        if not needs_fetch:
            frame = self._prepare_fundamental_frame(fundamental_data)
            self._record_fundamental_diagnostics(frame, all_symbols)
            return frame

        rate_limit_hits = 0
        last_reset = time.time()
        requests_this_minute = 0
        today_str = self._now_market().strftime("%Y-%m-%d")
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
                fundamental_fetched_at = (
                    self._now_market().to_pydatetime().isoformat(timespec="seconds")
                )
                fundamental_data.append({
                    "Symbol": symbol,
                    "Company": self._company_name(info, symbol),
                    "Cached_Date": today_str,
                    "Fundamental_As_Of": fundamental_fetched_at,
                    "Fundamental_Fetched_At": fundamental_fetched_at,
                    "Fundamental_As_Of_Quality": "fetch_timestamp",
                    "Fundamental_Source": "Yahoo Finance quote metadata",
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
                    "Dividend_Rate": info.get("dividendRate"),
                    "Market_Cap": info.get("marketCap"),
                    "EV_EBITDA": info.get("enterpriseToEbitda"),
                    "EBITDA": info.get("ebitda"),
                    "Free_CashFlow": info.get("freeCashflow"),
                    "Total_Debt": info.get("totalDebt"),
                    "Total_Cash": info.get("totalCash"),
                    "Total_Revenue": info.get("totalRevenue"),
                    "Shares_Outstanding": info.get("sharesOutstanding"),
                    "Book_Value": info.get("bookValue"),
                    "Sector": info.get("sector"),
                    "Industry": info.get("industry"),
                    "Fund_Data_Stale": False,
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

        # A transient Yahoo failure should not silently remove a company from
        # the inner merge and bias the ranking universe. Retain its expired row
        # as an explicitly stale fallback; the scorer caps it below BUY and the
        # old Cached_Date ensures the next run retries the refresh.
        fetched_symbols = {str(record["Symbol"]) for record in fundamental_data}
        fallback_symbols = all_symbols - fetched_symbols
        if fallback_symbols and not cached_df.empty:
            stale_fallback = cached_df[cached_df["Symbol"].astype(str).isin(fallback_symbols)].copy()
            if not stale_fallback.empty:
                stale_fallback["Fund_Data_Stale"] = True
                fundamental_data.extend(stale_fallback.to_dict("records"))
                logger.warning(
                    f"Using stale fundamental fallback for {len(stale_fallback)} stock(s); "
                    "their recommendations are capped below BUY"
                )

        fundamental_frame = self._prepare_fundamental_frame(fundamental_data)
        try:
            fundamental_frame.to_csv(cache_file, index=False)
            logger.info(f"Fundamental cache saved ({len(fundamental_data)} records)")
        except Exception as e:
            logger.warning(f"Fundamental cache save failed: {e}")
        self._record_fundamental_diagnostics(fundamental_frame, all_symbols)
        return fundamental_frame
