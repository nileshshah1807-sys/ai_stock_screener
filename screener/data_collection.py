"""NSE universe, price history, and fundamentals collection."""

import io
import logging
import time
from datetime import datetime

import pandas as pd
import requests
import yfinance as yf

from .market_data import PriceCache, TechnicalEnhancer

logger = logging.getLogger(__name__)

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
                        ma50_series = closes.rolling(50).mean()
                        ma50 = float(ma50_series.iloc[-1])
                        # MA50 slope (now vs ~20 trading days ago) - price sitting close to a
                        # still-FALLING MA50 is not the same as genuine strength, it just means
                        # price has caught up to a declining average. Used to adjust the MA50
                        # distance score in score_technical() instead of rewarding closeness blindly.
                        if len(ma50_series) >= 21 and pd.notna(ma50_series.iloc[-21]) and ma50_series.iloc[-21] != 0:
                            ma50_slope_pct = ((ma50 / float(ma50_series.iloc[-21])) - 1) * 100
                        else:
                            ma50_slope_pct = 0.0
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
                        adx_val, adx_plus_di, adx_minus_di = TechnicalEnhancer.calculate_adx(high, low, closes, 14)
                        stoch_rsi_val = TechnicalEnhancer.calculate_stoch_rsi(closes, 14)
                        atr_val = TechnicalEnhancer.calculate_atr(high, low, closes, 14)
                        results.append({
                            "Symbol": clean_sym,
                            "Current_Price": round(current_price, 2),
                            "MA20": round(ma20, 2),
                            "MA50": round(ma50, 2),
                            "MA50_Slope_Pct": round(ma50_slope_pct, 2),
                            "RSI_14": round(current_rsi, 2),
                            "Technical_Indicator_Version": 2,
                            "MACD": round(float(macd.iloc[-1]), 4),
                            "MACD_Signal": round(float(signal.iloc[-1]), 4),
                            "ADX_14": round(adx_val, 2),
                            "ADX_Plus_DI": round(adx_plus_di, 2),
                            "ADX_Minus_DI": round(adx_minus_di, 2),
                            "StochRSI_14": round(stoch_rsi_val, 2),
                            "ATR_14": round(atr_val, 2),
                            "High_6M": round(float(closes.max()), 2),
                            "Low_6M": round(float(closes.min()), 2),
                            "Pct_Change_1M": round(pct_1m, 2),
                            "Pct_Change_3M": round(pct_3m, 2),
                            "Pct_Change_6M": round(pct_6m, 2),
                            "Avg_Volume": int(avg_volume),
                            "Avg_Turnover_INR": round(avg_volume * current_price, 2),
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
    REQUIRED_FUND_COLUMNS = ("Company", "Sector", "Industry", "Total_Debt", "Total_Cash")

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
                    "Company": self._company_name(info, symbol),
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
