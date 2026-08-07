"""Fundamental and technical scoring models."""

import logging

import numpy as np
import pandas as pd

from .runtime import Config

logger = logging.getLogger(__name__)

# =====================================================
FUND_KEY_FIELDS = ("PE_Ratio", "ROE", "Profit_Margin", "Revenue_Growth")

# Metrics eligible for sector-relative (percentile-rank) fundamental scoring, mapped
# to the "scores" dict key used in score_fundamentals(), the metric's max points in
# that function, and whether a HIGHER raw value is better (False = lower is better,
# e.g. PE/Debt-to-Equity/EV-EBITDA where cheaper/less-levered scores higher).
SECTOR_RELATIVE_FIELDS = {
    "PE_Ratio":        ("PE", 15, False),
    "PB_Ratio":        ("PB", 8, False),
    "ROE":             ("ROE", 15, True),
    "ROA":             ("ROA", 5, True),
    "Debt_to_Equity":  ("DE", 10, False),
    "Current_Ratio":   ("CR", 7, True),
    "Profit_Margin":   ("PM", 10, True),
    "Revenue_Growth":  ("RG", 10, True),
    "Earnings_Growth": ("EG", 10, True),
    "Dividend_Yield":  ("DY", 5, True),
    "EV_EBITDA":       ("EV", 5, False),
}
# Reverse lookup: scores-dict key -> source column, used inside score_fundamentals()
SECTOR_RELATIVE_COLUMN_BY_KEY = {key: col for col, (key, _, _) in SECTOR_RELATIVE_FIELDS.items()}
RATING_ORDER = {"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "REDUCE": 3, "SELL": 4}
FINANCIAL_MODEL_NAMES = {
    "Bank Equity Quality Model",
    "NBFC Equity Quality Model",
    "Capital Markets Earnings Quality Model",
    "Insurance Equity Quality Model",
    "Financial Services Data-Limited Model",
}


def sort_by_recommendation(df, score_column):
    """Order recommendation classes first, then score within each class."""
    return (
        df.assign(_Rating_Order=df["Rating"].map(RATING_ORDER).fillna(len(RATING_ORDER)))
        .sort_values(["_Rating_Order", score_column], ascending=[True, False])
        .drop(columns="_Rating_Order")
        .reset_index(drop=True)
    )


def sector_relative_fund_scores(merged_df, min_peers=5):
    """Percentile-rank each fundamental metric against same-sector peers in the
    current scan, instead of a single fixed absolute threshold.

    A PE of 18 might be cheap for an IT stock but expensive for a Utility - this
    compares each stock to the other same-sector names actually being scored
    today rather than one universal bar. Returns a DataFrame (same index as
    merged_df) of per-column scores already expressed on that column's normal
    point scale (see SECTOR_RELATIVE_FIELDS); cells are NaN wherever the stock's
    own value is missing or its sector has fewer than ``min_peers`` members, so
    the caller can fall back to the absolute-threshold score for those cases.
    """
    if merged_df is None or len(merged_df) == 0:
        return pd.DataFrame(index=merged_df.index if merged_df is not None else None)

    sector = merged_df.get("Sector")
    if sector is None:
        sector = pd.Series("Unknown", index=merged_df.index)
    sector = sector.fillna("Unknown").astype(str).str.strip().replace("", "Unknown")
    # "Unknown" is not a sector. Ranking every missing-sector company against
    # every other missing-sector company silently compares banks, manufacturers,
    # and microcaps as if they were peers; fall back to absolute scoring instead.
    valid_sector = sector != "Unknown"

    out = pd.DataFrame(index=merged_df.index)
    for column, (_, max_pts, higher_is_better) in SECTOR_RELATIVE_FIELDS.items():
        if column not in merged_df:
            out[column] = np.nan
            continue
        values = pd.to_numeric(merged_df[column], errors="coerce")
        group_size = values.groupby(sector).transform("count")
        raw_rank = values.groupby(sector).rank(method="average")
        # Map every peer group symmetrically onto [0, 1]. pandas rank(pct=True)
        # maps ranks to [1/n, 1], so inverting it gives lower-is-better metrics
        # [0, (n-1)/n] and unfairly prevents the best value from scoring full
        # points. The explicit (rank - 1) / (n - 1) transform avoids that bias.
        pct_rank = (raw_rank - 1.0) / (group_size - 1.0)
        if not higher_is_better:
            pct_rank = 1.0 - pct_rank
        score = pct_rank * max_pts
        score = score.where((group_size >= min_peers) & valid_sector)
        out[column] = score
    return out


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
        specialized_sectors = {
            str(sector).strip().upper()
            for sector in getattr(self.config, "SPECIALIZED_FUNDAMENTAL_SECTORS", [])
            if str(sector).strip()
        }

        sector_rel_df = None
        if getattr(self.config, "SECTOR_RELATIVE_FUND_SCORING_ENABLED", True):
            min_peers = getattr(self.config, "MIN_SECTOR_PEERS", 5)
            sector_rel_df = sector_relative_fund_scores(merged_df, min_peers=min_peers)
        sector_relative_weight = getattr(self.config, "SECTOR_RELATIVE_FUND_WEIGHT", 0.5)

        for idx, row in merged_df.iterrows():
            sector_relative = sector_rel_df.loc[idx] if sector_rel_df is not None else None
            fundamental_model = fundamental_model_for_row(row)
            if fundamental_model in FINANCIAL_MODEL_NAMES:
                fund_components = score_financial_services(
                    row, fundamental_model=fundamental_model, return_components=True
                )
            elif fundamental_model == "Real Estate Asset Model":
                fund_components = score_real_estate(row, return_components=True)
            else:
                fund_components = score_fundamentals(
                    row, sector_relative, sector_relative_weight, return_components=True
                )
            f_raw = sum(fund_components.values())
            t_raw = self.score_technical(row)

            # normalize both to 0-100
            f_score = round(max(0.0, min(100.0, f_raw / self.MAX_FUND_SCORE * 100)), 2)
            t_score = round(max(0.0, min(100.0, t_raw / self.MAX_TECH_SCORE * 100)), 2)

            # ATR already contributes an explicit volatility penalty inside the
            # technical score. Keep model weights stable rather than letting the
            # same noisy input also change the blend regime.
            price = StockScorer.safe_float(row.get("Current_Price"), 0) or 0
            atr = StockScorer.safe_float(row.get("ATR_14"), price * 0.01) or 0
            atr_pct = (atr / price * 100) if price > 0 else 2.0

            weight_fund, weight_tech = 0.70, 0.30
            combined = round(f_score * weight_fund + t_score * weight_tech, 2)

            # P2: data-completeness gate - thin-data stocks can't be rated above HOLD
            fields_present = sum(
                1 for k in FUND_KEY_FIELDS if StockScorer.safe_float(row.get(k)) is not None
            )
            data_quality = "FULL" if fields_present >= min_key_fields else "LOW"
            sector = str(row.get("Sector") or "").strip().upper()
            specialized_fundamental_model_required = (
                sector in specialized_sectors
                and fundamental_model in {
                    "Generic Fundamental Model",
                    "Financial Services Data-Limited Model",
                }
            )
            anomalies = fundamental_anomalies(row)
            severe_fundamental_anomaly = len(anomalies) >= 2
            specialized_quality_eligible, specialized_quality_reason = specialized_quality_gate(
                row, fundamental_model
            )

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

            rating_cap_reason = ""
            rating_capped = bool(gate_enabled and data_quality == "LOW" and combined >= 60)
            if rating_capped:
                rating_cap_reason = "insufficient fundamental data"
            if specialized_fundamental_model_required and combined >= 60:
                rating_capped = True
                rating_cap_reason = "sector requires specialized model"
            fund_data_stale = str(row.get("Fund_Data_Stale", "")).strip().lower() in {
                "1", "true", "yes"
            }
            if fund_data_stale and combined >= 60:
                rating_capped = True
                rating_cap_reason = "stale fundamental fallback"
            if severe_fundamental_anomaly and combined >= 60:
                rating_capped = True
                rating_cap_reason = "multiple fundamental data anomalies"
            # A high score assembled from valuation ratios and neutral indicators
            # is not a current buy signal. BUY requires basic positive price
            # structure; STRONG BUY additionally requires directional strength.
            growth_floor = float(getattr(self.config, "STRONG_BUY_MIN_GROWTH", 0.05))
            tech_floor = float(getattr(self.config, "STRONG_BUY_MIN_TECH_SCORE", 55.0))
            adx_floor = float(getattr(self.config, "STRONG_BUY_MIN_ADX", 20.0))
            buy_ma50_slope_floor = float(getattr(self.config, "BUY_MIN_MA50_SLOPE", 0.0))
            buy_3m_return_floor = float(getattr(self.config, "BUY_MIN_3M_RETURN", 0.0))
            revenue_growth = StockScorer.safe_float(row.get("Revenue_Growth"))
            earnings_growth = StockScorer.safe_float(row.get("Earnings_Growth"))
            has_growth = (
                (revenue_growth is not None and revenue_growth >= growth_floor)
                or (earnings_growth is not None and earnings_growth >= growth_floor)
            )
            ma50 = StockScorer.safe_float(row.get("MA50"))
            ma50_slope = StockScorer.safe_float(row.get("MA50_Slope_Pct"))
            pct_3m = StockScorer.safe_float(row.get("Pct_Change_3M"))
            adx = StockScorer.safe_float(row.get("ADX_14"))
            plus_di = StockScorer.safe_float(row.get("ADX_Plus_DI"))
            minus_di = StockScorer.safe_float(row.get("ADX_Minus_DI"))
            buy_gate_failures = []
            if price <= 0 or ma50 is None:
                buy_gate_failures.append("price/MA50 unavailable")
            elif price <= ma50:
                buy_gate_failures.append("price not above MA50")
            if ma50_slope is None:
                buy_gate_failures.append("MA50 slope unavailable")
            elif ma50_slope < buy_ma50_slope_floor:
                buy_gate_failures.append("MA50 falling")
            if pct_3m is None:
                buy_gate_failures.append("3M return unavailable")
            elif pct_3m <= buy_3m_return_floor:
                buy_gate_failures.append("3M return not positive")

            buy_eligible = not buy_gate_failures
            trend_confirmed = buy_eligible and all([
                adx is not None and adx >= adx_floor,
                plus_di is not None and minus_di is not None and plus_di > minus_di,
            ])
            require_uptrend_for_buy = bool(getattr(self.config, "REQUIRE_UPTREND_FOR_BUY", True))
            technical_rating_capped = bool(
                require_uptrend_for_buy and combined >= 60 and not buy_eligible
            )
            if technical_rating_capped:
                technical_reason = "buy trend not confirmed: " + ", ".join(buy_gate_failures)
                rating_cap_reason = "; ".join(
                    reason for reason in (rating_cap_reason, technical_reason) if reason
                )
                rating_capped = True
            if rating_capped:
                rating = "HOLD"

            strong_buy_eligible = bool(
                has_growth
                and trend_confirmed
                and t_score >= tech_floor
                and specialized_quality_eligible
                and not anomalies
                and not rating_capped
            )
            strong_buy_gate_reason = ""
            if not specialized_quality_eligible:
                strong_buy_gate_reason = specialized_quality_reason
            elif anomalies:
                strong_buy_gate_reason = "fundamental anomaly: " + ", ".join(anomalies)
            elif not has_growth:
                strong_buy_gate_reason = "growth below threshold"
            elif not trend_confirmed:
                strong_buy_gate_reason = "trend not confirmed"
            elif t_score < tech_floor:
                strong_buy_gate_reason = "technical score below threshold"
            elif specialized_fundamental_model_required:
                strong_buy_gate_reason = "sector requires specialized model"
            elif rating_capped:
                strong_buy_gate_reason = rating_cap_reason
            if rating == "STRONG BUY" and not strong_buy_eligible:
                rating = "BUY"

            merged_df.at[idx, "Fundamental_Score"] = f_score
            merged_df.at[idx, "Technical_Score"] = t_score
            merged_df.at[idx, "ATR_Pct"] = round(atr_pct, 2)
            merged_df.at[idx, "Dynamic_Weight_Fund"] = weight_fund
            merged_df.at[idx, "Dynamic_Weight_Tech"] = weight_tech
            merged_df.at[idx, "Combined_Score"] = combined
            merged_df.at[idx, "Fund_Fields_Present"] = fields_present
            merged_df.at[idx, "Data_Quality"] = data_quality
            merged_df.at[idx, "Rating_Capped"] = rating_capped
            merged_df.at[idx, "Rating_Cap_Reason"] = rating_cap_reason
            merged_df.at[idx, "Specialized_Fundamental_Model_Required"] = specialized_fundamental_model_required
            merged_df.at[idx, "Fundamental_Model"] = fundamental_model
            valuation_keys = {"PE", "PB", "PB_ROE", "EV"}
            growth_keys = {"RG", "EG"}
            income_keys = {"DY"}
            valuation_points = sum(
                value for key, value in fund_components.items() if key in valuation_keys
            )
            growth_points = sum(
                value for key, value in fund_components.items() if key in growth_keys
            )
            income_points = sum(
                value for key, value in fund_components.items() if key in income_keys
            )
            quality_points = f_raw - valuation_points - growth_points - income_points
            merged_df.at[idx, "Fund_Valuation_Points"] = round(valuation_points, 2)
            merged_df.at[idx, "Fund_Quality_Points"] = round(quality_points, 2)
            merged_df.at[idx, "Fund_Growth_Points"] = round(growth_points, 2)
            merged_df.at[idx, "Fund_Income_Points"] = round(income_points, 2)
            merged_df.at[idx, "Fund_Component_Summary"] = (
                f"Val {valuation_points:.1f} | Quality {quality_points:.1f} | "
                f"Growth {growth_points:.1f} | Income {income_points:.1f}"
            )
            for component, points in fund_components.items():
                merged_df.at[idx, f"Fund_Component_{component}"] = round(points, 2)
            merged_df.at[idx, "Fundamental_Anomaly"] = bool(anomalies)
            merged_df.at[idx, "Fundamental_Anomaly_Reason"] = ", ".join(anomalies)
            merged_df.at[idx, "Specialized_Quality_Eligible"] = specialized_quality_eligible
            merged_df.at[idx, "Specialized_Quality_Gate_Reason"] = specialized_quality_reason
            merged_df.at[idx, "Buy_Eligible"] = buy_eligible
            merged_df.at[idx, "Buy_Gate_Reason"] = ", ".join(buy_gate_failures)
            merged_df.at[idx, "Strong_Buy_Eligible"] = strong_buy_eligible
            merged_df.at[idx, "Strong_Buy_Gate_Reason"] = strong_buy_gate_reason
            merged_df.at[idx, "Trend_Confirmed"] = trend_confirmed
            merged_df.at[idx, "Rating"] = rating

        merged_df = sort_by_recommendation(merged_df, "Combined_Score")
        merged_df["Rank"] = range(1, len(merged_df) + 1)

        n_capped = int(merged_df["Rating_Capped"].sum()) if "Rating_Capped" in merged_df else 0
        if n_capped:
            logger.info(f"Recommendation cap: {n_capped} stock(s) capped at HOLD")
        return merged_df

    @staticmethod
    def score_technical(row):
        s = StockScorer.safe_float
        scores = {}

        rsi = s(row.get("RSI_14"), 50)
        # Mid-range RSI is neutral, not a bullish signal. The prior 20-point
        # reward was the largest technical component and let directionless names
        # score well simply for not being overbought or oversold.
        if 40 <= rsi <= 60: scores["RSI"] = 12
        elif 30 <= rsi < 40 or 60 < rsi <= 70: scores["RSI"] = 10
        elif 20 <= rsi < 30 or 70 < rsi <= 80: scores["RSI"] = 6
        elif rsi < 20: scores["RSI"] = 4
        else: scores["RSI"] = 3

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

        # MA50 slope: being close to the MA only means genuine strength if that MA
        # is itself rising. A stock that has simply caught up to a still-FALLING
        # MA50 (e.g. after a sharp decline) should not get the same reward as one
        # consolidating near a rising MA50 - adjust the distance score above instead
        # of rewarding "closeness" blindly.
        ma50_slope = s(row.get("MA50_Slope_Pct"), 0) or 0
        if ma50_slope < -3:
            scores["MA50"] = max(1, scores["MA50"] - 6)
        elif ma50_slope < 0:
            scores["MA50"] = max(1, scores["MA50"] - 3)
        elif ma50_slope > 3:
            scores["MA50"] = min(15, scores["MA50"] + 2)

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

        # Momentum must distinguish actual gains from a flat price. Previously
        # 0% to +5% received almost the same reward as a healthy +5% to +15%
        # move, which inflated directionless charts.
        pct_1m = s(row.get("Pct_Change_1M"), 0) or 0
        if 5 <= pct_1m <= 15: scores["MOM"] = 20
        elif 0 < pct_1m < 5 or 15 < pct_1m <= 25: scores["MOM"] = 14
        elif pct_1m == 0: scores["MOM"] = 8
        elif -5 <= pct_1m < 0: scores["MOM"] = 6
        elif pct_1m > 25: scores["MOM"] = 8
        else: scores["MOM"] = 2

        bb_pos = s(row.get("BB_Position"), 0.5)
        if bb_pos is None: bb_pos = 0.5
        # The middle of the Bollinger range is neutral; it is not a breakout.
        if 0.3 <= bb_pos <= 0.7: scores["BB"] = 6
        elif 0.1 <= bb_pos < 0.3: scores["BB"] = 8
        elif 0.7 < bb_pos <= 0.9: scores["BB"] = 6
        elif bb_pos < 0.1: scores["BB"] = 7
        else: scores["BB"] = 3

        adx_val = s(row.get("ADX_14"), 25) or 25
        plus_di = s(row.get("ADX_Plus_DI"))
        minus_di = s(row.get("ADX_Minus_DI"))
        # ADX measures trend STRENGTH only, not direction - a strong downtrend
        # produces just as high an ADX reading as a strong uptrend. Use +DI/-DI to
        # tell them apart: only reward strength when bulls are in control
        # (+DI > -DI); flip it into a matching penalty when bears are in control.
        is_downtrend = plus_di is not None and minus_di is not None and minus_di > plus_di
        if adx_val > 40: scores["ADX"] = 1 if is_downtrend else 12
        elif adx_val > 30: scores["ADX"] = 2 if is_downtrend else 10
        elif adx_val > 20: scores["ADX"] = 4 if is_downtrend else 7
        else: scores["ADX"] = 3

        stoch_rsi = s(row.get("StochRSI_14"), 50)
        if stoch_rsi is None: stoch_rsi = 50
        if stoch_rsi <= 0 or stoch_rsi >= 100:
            # Exact 0/100 readings are usually degenerate (illiquid names with
            # near-zero price variance over the lookback window) rather than
            # a genuine reversal signal - score neutrally instead of
            # rewarding/penalizing at the extreme.
            scores["STOCH"] = 6
        elif stoch_rsi > 80: scores["STOCH"] = 5
        elif stoch_rsi < 20:
            # "Oversold" is only a genuine mean-reversion signal when the
            # stock isn't already confirmed to be in a strong downtrend (see
            # +DI/-DI above) - a falling knife isn't a buy signal just
            # because StochRSI is low.
            scores["STOCH"] = 6 if is_downtrend else 12
        elif 30 <= stoch_rsi <= 70: scores["STOCH"] = 8
        else: scores["STOCH"] = 6

        atr_val = s(row.get("ATR_14"), price * 0.01)
        atr_pct = (atr_val / price * 100) if price > 0 and atr_val else 5.0
        if atr_pct < 1: scores["ATR"] = 8
        elif atr_pct < 2: scores["ATR"] = 6
        elif atr_pct < 4: scores["ATR"] = 4
        else: scores["ATR"] = 2

        return sum(scores.values())

def fundamental_model_for_row(row):
    sector = str(row.get("Sector") or "").strip().upper()
    if sector == "FINANCIAL SERVICES":
        industry = str(row.get("Industry") or "").strip().upper()
        if "BANK" in industry:
            return "Bank Equity Quality Model"
        if any(term in industry for term in ("CREDIT SERVICES", "MORTGAGE", "CONSUMER FINANCE")):
            return "NBFC Equity Quality Model"
        if any(term in industry for term in ("CAPITAL MARKET", "ASSET MANAGEMENT", "BROKER", "EXCHANGE")):
            return "Capital Markets Earnings Quality Model"
        if "INSURANCE" in industry:
            return "Insurance Equity Quality Model"
        return "Financial Services Data-Limited Model"
    if sector == "REAL ESTATE":
        return "Real Estate Asset Model"
    return "Generic Fundamental Model"


def fundamental_anomalies(row):
    """Return severe point-in-time data patterns that need manual validation."""
    s = StockScorer.safe_float
    checks = (
        ("PE_Ratio", lambda value: 0 < value < 1, "PE below 1"),
        ("ROE", lambda value: abs(value) > 1, "absolute ROE above 100%"),
        ("ROA", lambda value: abs(value) > 0.5, "absolute ROA above 50%"),
        ("Profit_Margin", lambda value: abs(value) > 1, "absolute margin above 100%"),
        ("Revenue_Growth", lambda value: value > 2 or value <= -1, "extreme revenue growth"),
        ("Earnings_Growth", lambda value: value > 2 or value <= -1, "extreme earnings growth"),
    )
    anomalies = []
    for field, predicate, message in checks:
        value = s(row.get(field))
        if value is not None and predicate(value):
            anomalies.append(message)
    return anomalies


def specialized_quality_gate(row, fundamental_model):
    """High-conviction financial labels require sector-specific risk inputs."""
    s = StockScorer.safe_float
    required_by_model = {
        "Bank Equity Quality Model": (
            "Gross_NPA", "Net_NPA", "Capital_Adequacy",
        ),
        "NBFC Equity Quality Model": (
            "Gross_NPA", "Net_NPA", "Capital_Adequacy",
        ),
        "Insurance Equity Quality Model": ("Solvency_Ratio",),
        "Capital Markets Earnings Quality Model": (
            "ROE", "ROA", "Profit_Margin",
        ),
    }
    if fundamental_model == "Financial Services Data-Limited Model":
        return False, "financial sub-industry requires a dedicated model"
    required = required_by_model.get(fundamental_model)
    if not required:
        return True, "passed"
    missing = [field for field in required if s(row.get(field)) is None]
    if missing:
        return False, "missing specialized quality data: " + ", ".join(missing)

    if fundamental_model in {"Bank Equity Quality Model", "NBFC Equity Quality Model"}:
        gross_npa, net_npa, capital_adequacy = _financial_quality_percentages(row)
        failures = []
        if gross_npa > 8.0:
            failures.append(f"Gross NPA {gross_npa:.1f}% above 8%")
        if net_npa > 4.0:
            failures.append(f"Net NPA {net_npa:.1f}% above 4%")
        if capital_adequacy < 12.0:
            failures.append(f"capital adequacy {capital_adequacy:.1f}% below 12%")
        if failures:
            return False, "specialized quality threshold failed: " + ", ".join(failures)

    if fundamental_model == "Insurance Equity Quality Model":
        solvency = s(row.get("Solvency_Ratio"))
        if solvency is not None and solvency > 10:
            solvency /= 100.0
        if solvency is None or solvency < 1.5:
            return False, "specialized quality threshold failed: solvency below 1.5x"
    return True, "passed"


def _financial_quality_percentages(row):
    """Normalize NPA/CAR fields using capital adequacy to infer row units."""
    s = StockScorer.safe_float
    capital_adequacy = s(row.get("Capital_Adequacy"))
    values_are_ratios = capital_adequacy is not None and abs(capital_adequacy) <= 1.0

    def normalize(field):
        value = s(row.get(field))
        if value is None:
            return None
        return value * 100.0 if values_are_ratios else value

    return normalize("Gross_NPA"), normalize("Net_NPA"), normalize("Capital_Adequacy")


def _bank_risk_points(row, gross_max, net_max, capital_max, nbfc=False):
    gross_npa, net_npa, capital_adequacy = _financial_quality_percentages(row)
    gross_good = 3.0 if nbfc else 2.0
    net_good = 1.5 if nbfc else 1.0
    return {
        "GROSS_NPA": 0.0 if gross_npa is None else (
            float(gross_max) if gross_npa <= gross_good
            else round(gross_max * 0.70, 2) if gross_npa <= 4.0
            else round(gross_max * 0.35, 2) if gross_npa <= 8.0
            else 0.0
        ),
        "NET_NPA": 0.0 if net_npa is None else (
            float(net_max) if net_npa <= net_good
            else round(net_max * 0.70, 2) if net_npa <= 2.0
            else round(net_max * 0.35, 2) if net_npa <= 4.0
            else 0.0
        ),
        "CAPITAL_ADEQUACY": 0.0 if capital_adequacy is None else (
            float(capital_max) if capital_adequacy >= 18.0
            else round(capital_max * 0.80, 2) if capital_adequacy >= 15.0
            else round(capital_max * 0.50, 2) if capital_adequacy >= 12.0
            else 0.0
        ),
    }


def _pe_points(pe, max_points):
    if pe is None or pe <= 0:
        return 0.0
    if pe < 1:
        return round(max_points * 0.30, 2)
    if pe < 10:
        return float(max_points)
    if pe < 18:
        return round(max_points * 0.85, 2)
    if pe < 25:
        return round(max_points * 0.67, 2)
    if pe < 40:
        return round(max_points * 0.40, 2)
    return round(max_points * 0.20, 2)


def _pb_roe_points(pb, roe, max_points):
    """Reward cheap book value only when the equity earns an adequate return."""
    if pb is None or pb <= 0 or roe is None:
        return 0.0
    if roe < 0:
        base = 1
    elif roe >= 0.18:
        base = 20 if pb <= 2 else 16 if pb <= 3 else 10
    elif roe >= 0.15:
        base = 17 if pb <= 1.5 else 14 if pb <= 2.5 else 8
    elif roe >= 0.12:
        base = 14 if pb <= 1.25 else 11 if pb <= 2 else 6
    elif roe >= 0.10:
        base = 10 if pb <= 1 else 8 if pb <= 1.5 else 4
    else:
        base = 4 if pb < 1 else 2
    return round(base / 20 * max_points, 2)


def _roe_points(value, max_points):
    if value is None:
        return 0.0
    if abs(value) > 1:
        return round(max_points * 0.30, 2)
    if value >= 0.20:
        return float(max_points)
    if value >= 0.15:
        return round(max_points * 0.80, 2)
    if value >= 0.10:
        return round(max_points * 0.55, 2)
    if value >= 0:
        return round(max_points * 0.30, 2)
    return round(max_points * 0.10, 2)


def _roa_points(value, max_points):
    if value is None:
        return 0.0
    if abs(value) > 0.5:
        return round(max_points * 0.20, 2)
    if value >= 0.03:
        return float(max_points)
    if value >= 0.02:
        return round(max_points * 0.80, 2)
    if value >= 0.01:
        return round(max_points * 0.60, 2)
    if value >= 0:
        return round(max_points * 0.30, 2)
    return round(max_points * 0.10, 2)


def _profit_points(value, max_points):
    if value is None:
        return 0.0
    if abs(value) > 1:
        return round(max_points * 0.30, 2)
    if value >= 0.20:
        return float(max_points)
    if value >= 0.12:
        return round(max_points * 0.80, 2)
    if value >= 0.05:
        return round(max_points * 0.55, 2)
    if value >= 0:
        return round(max_points * 0.30, 2)
    return round(max_points * 0.10, 2)


def _growth_points(value, max_points, strong_threshold=0.20):
    if value is None:
        return 0.0
    if value > 2 or value <= -1:
        return round(max_points * 0.30, 2)
    if value >= strong_threshold:
        return float(max_points)
    if value >= 0.10:
        return round(max_points * 0.80, 2)
    if value >= 0.05:
        return round(max_points * 0.60, 2)
    if value >= 0:
        return round(max_points * 0.30, 2)
    return round(max_points * 0.10, 2)


def _dividend_points(value, max_points=5):
    if value is None or value <= 0:
        return 0.0
    if value >= 0.03:
        return float(max_points)
    if value >= 0.015:
        return round(max_points * 0.80, 2)
    return round(max_points * 0.60, 2)


def score_financial_services(row, fundamental_model=None, return_components=False):
    """Industry-specific equity models; never use debt as a bank quality input."""
    s = StockScorer.safe_float
    model = fundamental_model or fundamental_model_for_row(row)
    pe = s(row.get("PE_Ratio"))
    pb = s(row.get("PB_Ratio"))
    roe = s(row.get("ROE"))
    roa = s(row.get("ROA"))
    margin = s(row.get("Profit_Margin"))
    revenue_growth = s(row.get("Revenue_Growth"))
    earnings_growth = s(row.get("Earnings_Growth"))
    dividend_yield = s(row.get("Dividend_Yield"))

    if model == "Bank Equity Quality Model":
        scores = {
            "PE": _pe_points(pe, 10),
            "PB_ROE": _pb_roe_points(pb, roe, 15),
            "ROE": _roe_points(roe, 15),
            "ROA": _roa_points(roa, 10),
            "PM": _profit_points(margin, 5),
            "RG": _growth_points(revenue_growth, 8, 0.15),
            "EG": _growth_points(earnings_growth, 7),
            "DY": _dividend_points(dividend_yield),
        }
        scores.update(_bank_risk_points(row, gross_max=8, net_max=7, capital_max=10))
    elif model == "NBFC Equity Quality Model":
        scores = {
            "PE": _pe_points(pe, 10),
            "PB_ROE": _pb_roe_points(pb, roe, 15),
            "ROE": _roe_points(roe, 15),
            "ROA": _roa_points(roa, 10),
            "PM": _profit_points(margin, 5),
            "RG": _growth_points(revenue_growth, 10, 0.15),
            "EG": _growth_points(earnings_growth, 10),
            "DY": _dividend_points(dividend_yield),
        }
        scores.update(
            _bank_risk_points(row, gross_max=6, net_max=5, capital_max=9, nbfc=True)
        )
    elif model == "Insurance Equity Quality Model":
        solvency = s(row.get("Solvency_Ratio"))
        scores = {
            "PE": _pe_points(pe, 15),
            "PB_ROE": _pb_roe_points(pb, roe, 15),
            "ROE": _roe_points(roe, 20),
            "ROA": _roa_points(roa, 10),
            "PM": _profit_points(margin, 10),
            "RG": _growth_points(revenue_growth, 10, 0.15),
            "EG": _growth_points(earnings_growth, 10),
            "DY": _dividend_points(dividend_yield),
            "SOLVENCY": 5.0 if solvency is not None and solvency >= 1.5 else 0.0,
        }
    else:
        # Capital-markets and unknown financial firms use earnings-quality
        # inputs. Unknown industries are separately capped by the model gate.
        scores = {
            "PE": _pe_points(pe, 15),
            "PB_ROE": _pb_roe_points(pb, roe, 15),
            "ROE": _roe_points(roe, 20),
            "ROA": _roa_points(roa, 10),
            "PM": _profit_points(margin, 15),
            "RG": _growth_points(revenue_growth, 10, 0.15),
            "EG": _growth_points(earnings_growth, 10),
            "DY": _dividend_points(dividend_yield),
        }
    return scores if return_components else sum(scores.values())


def score_real_estate(row, return_components=False):
    """Asset, leverage, profitability, and growth model for real-estate firms."""
    s = StockScorer.safe_float
    scores = {}

    pe = s(row.get("PE_Ratio"))
    scores["PE"] = _pe_points(pe, 15)

    pb = s(row.get("PB_Ratio"))
    roe = s(row.get("ROE"))
    scores["PB_ROE"] = _pb_roe_points(pb, roe, 15)

    debt_to_equity = s(row.get("Debt_to_Equity"))
    scores["DE"] = 0 if debt_to_equity is None else 15 if debt_to_equity < 30 else 12 if debt_to_equity < 70 else 7 if debt_to_equity < 120 else 3

    current_ratio = s(row.get("Current_Ratio"))
    scores["CR"] = 0 if current_ratio is None else 10 if current_ratio >= 1.5 else 7 if current_ratio >= 1.0 else 3

    margin = s(row.get("Profit_Margin"))
    scores["PM"] = _profit_points(margin, 15)

    revenue_growth = s(row.get("Revenue_Growth"))
    scores["RG"] = _growth_points(revenue_growth, 15)

    earnings_growth = s(row.get("Earnings_Growth"))
    scores["EG"] = _growth_points(earnings_growth, 15)
    return scores if return_components else sum(scores.values())


def score_fundamentals(
    row,
    sector_relative=None,
    sector_relative_weight=0.5,
    return_components=False,
):
    """Fundamental quality/valuation score, raw max = 100.

    ``sector_relative`` (optional) is a mapping of column -> percentile-based
    score (see ``sector_relative_fund_scores``) for the metrics that vary a lot
    by sector. When present and not NaN for a given metric, it is blended with
    the fixed absolute-threshold score below (weight = ``sector_relative_weight``),
    so e.g. a PE of 18 is judged partly against other same-sector names rather
    than a single universal bar that treats IT and Utilities identically.
    """
    s = StockScorer.safe_float
    scores = {}

    pe = s(row.get("PE_Ratio"))
    scores["PE"] = _pe_points(pe, 15)

    pb = s(row.get("PB_Ratio"))
    if pb is None or pb <= 0: scores["PB"] = 0
    elif pb < 2: scores["PB"] = 8
    elif pb < 4: scores["PB"] = 6
    elif pb < 8: scores["PB"] = 4
    else: scores["PB"] = 2

    roe = s(row.get("ROE"))
    scores["ROE"] = _roe_points(roe, 15)

    roa = s(row.get("ROA"))
    scores["ROA"] = _roa_points(roa, 5)

    de = s(row.get("Debt_to_Equity"))  # yfinance reports this as a percentage
    if de is None: scores["DE"] = 0
    elif de < 30: scores["DE"] = 10
    elif de < 70: scores["DE"] = 8
    elif de < 150: scores["DE"] = 5
    else: scores["DE"] = 2

    cr = s(row.get("Current_Ratio"))
    if cr is None: scores["CR"] = 0
    elif cr >= 2: scores["CR"] = 7
    elif cr >= 1.2: scores["CR"] = 5
    elif cr >= 1: scores["CR"] = 4
    else: scores["CR"] = 2

    pm = s(row.get("Profit_Margin"))
    scores["PM"] = _profit_points(pm, 10)

    rg = s(row.get("Revenue_Growth"))
    scores["RG"] = _growth_points(rg, 10)

    eg = s(row.get("Earnings_Growth"))
    scores["EG"] = _growth_points(eg, 10)

    dy = s(row.get("Dividend_Yield"))
    if dy is None or dy <= 0: scores["DY"] = 0
    elif dy >= 0.03: scores["DY"] = 5
    elif dy >= 0.015: scores["DY"] = 4
    else: scores["DY"] = 3

    ev = s(row.get("EV_EBITDA"))
    if ev is None or ev <= 0: scores["EV"] = 0
    elif ev < 10: scores["EV"] = 5
    elif ev < 18: scores["EV"] = 4
    elif ev < 30: scores["EV"] = 2
    else: scores["EV"] = 1

    if sector_relative is not None:
        weight = max(0.0, min(1.0, StockScorer.safe_float(sector_relative_weight, 0.5) or 0.0))
        if weight > 0:
            for key, column in SECTOR_RELATIVE_COLUMN_BY_KEY.items():
                sector_score = sector_relative.get(column) if hasattr(sector_relative, "get") else None
                if sector_score is None or (isinstance(sector_score, float) and pd.isna(sector_score)):
                    continue
                scores[key] = round(scores[key] * (1 - weight) + sector_score * weight, 2)

    # Hard guards are applied after peer-relative blending. A bad or suspect
    # absolute value must not become attractive merely because its peers are
    # similarly weak or because an extreme observation wins a percentile rank.
    if pe is not None and 0 < pe < 1:
        scores["PE"] = min(scores["PE"], 4.5)
    if pb is not None and 0 < pb < 2 and (roe is None or roe < 0.10):
        scores["PB"] = min(scores["PB"], 4.0)
    if roe is not None and abs(roe) > 1:
        scores["ROE"] = min(scores["ROE"], 4.5)
    if roa is not None and abs(roa) > 0.5:
        scores["ROA"] = min(scores["ROA"], 1.0)
    if pm is not None and abs(pm) > 1:
        scores["PM"] = min(scores["PM"], 3.0)
    if rg is not None and (rg > 2 or rg <= -1):
        scores["RG"] = min(scores["RG"], 3.0)
    if eg is not None and (eg > 2 or eg <= -1):
        scores["EG"] = min(scores["EG"], 3.0)

    # Value-trap guard: a low PE/PB only reflects genuine undervaluation if the
    # business isn't actively shrinking. When BOTH revenue and earnings are
    # contracting, cap the reward for a "cheap" multiple - it's priced that way
    # for a reason, not because the market is missing a bargain. Applied after
    # sector-relative blending so it's a hard final cap regardless of how the
    # stock compares to its (possibly also-struggling) sector peers.
    is_shrinking = (eg is not None and eg < 0) and (rg is not None and rg < 0)
    if is_shrinking:
        if pe is not None and 0 < pe < 15:
            scores["PE"] = min(scores["PE"], 8)
        if pb is not None and 0 < pb < 2:
            scores["PB"] = min(scores["PB"], 5)

    return scores if return_components else sum(scores.values())
