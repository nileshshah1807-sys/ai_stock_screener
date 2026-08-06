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
        pct_rank = values.groupby(sector).rank(pct=True, method="average")
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
            if fundamental_model == "Financial Services Equity Model":
                f_raw = score_financial_services(row)
            elif fundamental_model == "Real Estate Asset Model":
                f_raw = score_real_estate(row)
            else:
                f_raw = score_fundamentals(row, sector_relative, sector_relative_weight)
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
            sector = str(row.get("Sector") or "").strip().upper()
            specialized_fundamental_model_required = (
                sector in specialized_sectors and fundamental_model == "Generic Fundamental Model"
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
            if rating_capped:
                rating = "HOLD"

            # A high score assembled from valuation ratios and neutral indicators
            # is not a high-conviction buy. Require both real business growth and
            # a confirmed uptrend before awarding STRONG BUY. This prevents names
            # such as XCHANGING - flat sales and no visible trend/participation -
            # from qualifying solely because they are cheap or mean-reverting.
            growth_floor = float(getattr(self.config, "STRONG_BUY_MIN_GROWTH", 0.05))
            tech_floor = float(getattr(self.config, "STRONG_BUY_MIN_TECH_SCORE", 55.0))
            adx_floor = float(getattr(self.config, "STRONG_BUY_MIN_ADX", 20.0))
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
            trend_confirmed = all([
                price > 0 and ma50 is not None and price > ma50,
                ma50_slope is not None and ma50_slope >= 0,
                pct_3m is not None and pct_3m > 0,
                adx is not None and adx >= adx_floor,
                plus_di is not None and minus_di is not None and plus_di > minus_di,
            ])
            strong_buy_eligible = bool(
                has_growth and trend_confirmed and t_score >= tech_floor and not rating_capped
            )
            strong_buy_gate_reason = ""
            if not has_growth:
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
        return "Financial Services Equity Model"
    if sector == "REAL ESTATE":
        return "Real Estate Asset Model"
    return "Generic Fundamental Model"


def score_financial_services(row):
    """Equity-value model for banks, insurers, NBFCs, and other financial firms."""
    s = StockScorer.safe_float
    score = 0

    pe = s(row.get("PE_Ratio"))
    score += 0 if pe is None or pe <= 0 else 15 if pe < 10 else 13 if pe < 18 else 10 if pe < 25 else 6 if pe < 40 else 3

    pb = s(row.get("PB_Ratio"))
    score += 0 if pb is None or pb <= 0 else 20 if pb < 1 else 16 if pb < 2 else 12 if pb < 3 else 7 if pb < 5 else 3

    roe = s(row.get("ROE"))
    score += 0 if roe is None else 20 if roe >= 0.20 else 16 if roe >= 0.15 else 11 if roe >= 0.10 else 6 if roe >= 0 else 2

    roa = s(row.get("ROA"))
    score += 0 if roa is None else 10 if roa >= 0.03 else 8 if roa >= 0.02 else 6 if roa >= 0.01 else 3 if roa >= 0 else 1

    margin = s(row.get("Profit_Margin"))
    score += 0 if margin is None else 10 if margin >= 0.20 else 8 if margin >= 0.12 else 5 if margin >= 0.05 else 3 if margin >= 0 else 1

    revenue_growth = s(row.get("Revenue_Growth"))
    score += 0 if revenue_growth is None else 10 if revenue_growth >= 0.15 else 8 if revenue_growth >= 0.08 else 6 if revenue_growth >= 0.03 else 3 if revenue_growth >= 0 else 1

    earnings_growth = s(row.get("Earnings_Growth"))
    score += 0 if earnings_growth is None else 10 if earnings_growth >= 0.20 else 8 if earnings_growth >= 0.10 else 6 if earnings_growth >= 0.05 else 3 if earnings_growth >= 0 else 1

    dividend_yield = s(row.get("Dividend_Yield"))
    score += 0 if dividend_yield is None or dividend_yield <= 0 else 5 if dividend_yield >= 0.03 else 4 if dividend_yield >= 0.015 else 3
    return score


def score_real_estate(row):
    """Asset, leverage, profitability, and growth model for real-estate firms."""
    s = StockScorer.safe_float
    score = 0

    pe = s(row.get("PE_Ratio"))
    score += 0 if pe is None or pe <= 0 else 15 if pe < 15 else 12 if pe < 25 else 8 if pe < 40 else 4

    pb = s(row.get("PB_Ratio"))
    score += 0 if pb is None or pb <= 0 else 15 if pb < 1.5 else 12 if pb < 3 else 8 if pb < 5 else 4

    debt_to_equity = s(row.get("Debt_to_Equity"))
    score += 0 if debt_to_equity is None else 15 if debt_to_equity < 30 else 12 if debt_to_equity < 70 else 7 if debt_to_equity < 120 else 3

    current_ratio = s(row.get("Current_Ratio"))
    score += 0 if current_ratio is None else 10 if current_ratio >= 1.5 else 7 if current_ratio >= 1.0 else 3

    margin = s(row.get("Profit_Margin"))
    score += 0 if margin is None else 15 if margin >= 0.20 else 12 if margin >= 0.12 else 8 if margin >= 0.05 else 4 if margin >= 0 else 1

    revenue_growth = s(row.get("Revenue_Growth"))
    score += 0 if revenue_growth is None else 15 if revenue_growth >= 0.20 else 12 if revenue_growth >= 0.10 else 8 if revenue_growth >= 0.05 else 4 if revenue_growth >= 0 else 1

    earnings_growth = s(row.get("Earnings_Growth"))
    score += 0 if earnings_growth is None else 15 if earnings_growth >= 0.20 else 12 if earnings_growth >= 0.10 else 8 if earnings_growth >= 0.05 else 4 if earnings_growth >= 0 else 1
    return score


def score_fundamentals(row, sector_relative=None, sector_relative_weight=0.5):
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
    if pe is None or pe <= 0: scores["PE"] = 0
    elif pe < 15: scores["PE"] = 15
    elif pe < 25: scores["PE"] = 12
    elif pe < 40: scores["PE"] = 8
    else: scores["PE"] = 4

    pb = s(row.get("PB_Ratio"))
    if pb is None or pb <= 0: scores["PB"] = 0
    elif pb < 2: scores["PB"] = 8
    elif pb < 4: scores["PB"] = 6
    elif pb < 8: scores["PB"] = 4
    else: scores["PB"] = 2

    roe = s(row.get("ROE"))
    if roe is None: scores["ROE"] = 0
    elif roe >= 0.25: scores["ROE"] = 15
    elif roe >= 0.15: scores["ROE"] = 12
    elif roe >= 0.10: scores["ROE"] = 8
    elif roe >= 0: scores["ROE"] = 5
    else: scores["ROE"] = 2

    roa = s(row.get("ROA"))
    if roa is None: scores["ROA"] = 0
    elif roa >= 0.10: scores["ROA"] = 5
    elif roa >= 0.05: scores["ROA"] = 4
    elif roa >= 0: scores["ROA"] = 3
    else: scores["ROA"] = 1

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
    if pm is None: scores["PM"] = 0
    elif pm >= 0.20: scores["PM"] = 10
    elif pm >= 0.10: scores["PM"] = 8
    elif pm >= 0.05: scores["PM"] = 6
    elif pm >= 0: scores["PM"] = 4
    else: scores["PM"] = 1

    rg = s(row.get("Revenue_Growth"))
    if rg is None: scores["RG"] = 0
    elif rg >= 0.20: scores["RG"] = 10
    elif rg >= 0.10: scores["RG"] = 8
    elif rg >= 0.05: scores["RG"] = 6
    elif rg >= 0: scores["RG"] = 4
    else: scores["RG"] = 2

    eg = s(row.get("Earnings_Growth"))
    if eg is None: scores["EG"] = 0
    elif eg >= 0.25: scores["EG"] = 10
    elif eg >= 0.15: scores["EG"] = 8
    elif eg >= 0.05: scores["EG"] = 6
    elif eg >= 0: scores["EG"] = 4
    else: scores["EG"] = 2

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

    return sum(scores.values())
