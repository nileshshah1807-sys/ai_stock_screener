"""Scoring schema: field maps, component tables and point capacities.

Pure data shared by the fundamental, sector and technical scorers. This module
imports nothing from the rest of the package, so every scoring module can
depend on it without creating a cycle.
"""

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
SECTOR_RELATIVE_MINIMUMS = {
    "PE_Ratio": 0.0,
    "PB_Ratio": 0.0,
    "EV_EBITDA": 0.0,
    "Debt_to_Equity": 0.0,
    "Current_Ratio": 0.0,
    "Dividend_Yield": 0.0,
}
RATING_ORDER = {"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "REDUCE": 3, "SELL": 4}
CANONICAL_DECISION_COLUMNS = {
    "Rating",
    "Rank",
    "Buy_Eligible",
    "Buy_Gate_Reason",
    "Buy_Gate_Failures",
    "Buy_Gate_Failure_Count",
    "Strong_Buy_Eligible",
    "Strong_Buy_Gate_Reason",
    "Strong_Buy_Gate_Failures",
    "Strong_Buy_Gate_Failure_Count",
    "Trend_Confirmed",
    "Rating_Capped",
    "Rating_Cap_Reason",
    "Gate_Failures",
    "Gate_Failure_Count",
    "Evidence_Score",
    "Evidence_Rating",
    "Decision_Score",
    "Decision_Rating",
    "Decision_Score_Ceiling",
    "Decision_Cap_Applied",
    "Decision_Cap_Reason",
    "Final_Score",
    "Score_Rank",
    "Recommendation_Rank",
    "Investment_Rank",
    "Actionable_Rank",
}
FINANCIAL_MODEL_NAMES = {
    "Bank Equity Quality Model",
    "NBFC Equity Quality Model",
    "Capital Markets Earnings Quality Model",
    "Insurance Equity Quality Model",
    "Financial Services Data-Limited Model",
}

# Technical evidence is scored component-by-component. Missing evidence has no
# hidden default points; the observed score is confidence-shrunk toward 50 by
# coverage. This makes an empty technical row exactly neutral with zero
# confidence instead of the previous implicit 62.12/100.
TECH_COMPONENT_MAX = {
    "RSI": 12.0,
    "MA20": 15.0,
    "MA50": 15.0,
    "MACD": 15.0,
    "VOL": 15.0,
    "MOM": 20.0,
    "BB": 8.0,
    "ADX": 12.0,
    "STOCH": 12.0,
    "ATR": 8.0,
}

GENERIC_FUNDAMENTAL_FIELDS = tuple(SECTOR_RELATIVE_FIELDS)
FINANCIAL_SPECIALIZED_FIELDS = {
    "Bank Equity Quality Model": (
        "PB_Ratio", "ROE", "Gross_NPA", "Net_NPA", "Capital_Adequacy",
        "Profit_Margin", "Revenue_Growth", "Earnings_Growth",
    ),
    "NBFC Equity Quality Model": (
        "PB_Ratio", "ROE", "Gross_NPA", "Net_NPA", "Capital_Adequacy",
        "Profit_Margin", "Revenue_Growth", "Earnings_Growth",
    ),
    "Insurance Equity Quality Model": (
        "PB_Ratio", "ROE", "Solvency_Ratio", "Profit_Margin",
        "Revenue_Growth", "Earnings_Growth",
    ),
    "Capital Markets Earnings Quality Model": (
        "PE_Ratio", "PB_Ratio", "ROE", "ROA", "Profit_Margin",
        "Revenue_Growth", "Earnings_Growth", "Dividend_Yield",
    ),
    "Financial Services Data-Limited Model": (
        "PE_Ratio", "PB_Ratio", "ROE", "Profit_Margin",
        "Revenue_Growth", "Earnings_Growth",
    ),
    "Real Estate Asset Model": (
        "PB_Ratio", "ROE", "Debt_to_Equity", "Current_Ratio",
        "Profit_Margin", "Revenue_Growth", "Earnings_Growth",
    ),
}

# Declared point capacity of every fundamental component, per model. Each model
# sums to MAX_FUND_SCORE. The scorers still own the point curves; these tables
# only describe how much capacity a component represents, so a component whose
# input was never reported can be removed from BOTH the numerator and the
# denominator instead of silently scoring zero -- which is what made an
# unreported ROA indistinguishable from the worst ROA in the market.
# ``test_fundamental_capacity_tables_match_scorers`` locks these against the
# scorers so the two cannot drift apart.
_CAPITAL_MARKETS_COMPONENT_MAX = {
    "PE": 15, "PB_ROE": 15, "ROE": 20, "ROA": 10,
    "PM": 15, "RG": 10, "EG": 10, "DY": 5,
}
FUNDAMENTAL_COMPONENT_MAX = {
    "Generic Fundamental Model": {
        "PE": 15, "PB": 8, "ROE": 15, "ROA": 5, "DE": 10, "CR": 7,
        "PM": 10, "RG": 10, "EG": 10, "DY": 5, "EV": 5,
    },
    "Bank Equity Quality Model": {
        "PE": 10, "PB_ROE": 15, "ROE": 15, "ROA": 10, "PM": 5, "RG": 8,
        "EG": 7, "DY": 5, "GROSS_NPA": 8, "NET_NPA": 7, "CAPITAL_ADEQUACY": 10,
    },
    "NBFC Equity Quality Model": {
        "PE": 10, "PB_ROE": 15, "ROE": 15, "ROA": 10, "PM": 5, "RG": 10,
        "EG": 10, "DY": 5, "GROSS_NPA": 6, "NET_NPA": 5, "CAPITAL_ADEQUACY": 9,
    },
    "Insurance Equity Quality Model": {
        "PE": 15, "PB_ROE": 15, "ROE": 20, "ROA": 10, "PM": 10, "RG": 10,
        "EG": 10, "DY": 5, "SOLVENCY": 5,
    },
    "Capital Markets Earnings Quality Model": _CAPITAL_MARKETS_COMPONENT_MAX,
    "Financial Services Data-Limited Model": _CAPITAL_MARKETS_COMPONENT_MAX,
    "Real Estate Asset Model": {
        "PE": 15, "PB_ROE": 15, "DE": 15, "CR": 10, "PM": 15, "RG": 15, "EG": 15,
    },
}

# Inputs a component needs before it can be called observed. The outer tuple is
# an AND of requirement groups; each inner tuple is an OR of interchangeable
# source columns.
FUNDAMENTAL_COMPONENT_INPUTS = {
    "PE": (("PE_Ratio",),),
    "PB": (("PB_Ratio",),),
    "PB_ROE": (("PB_Ratio",), ("ROE",)),
    "ROE": (("ROE",),),
    "ROA": (("ROA",),),
    "DE": (("Debt_to_Equity",),),
    "CR": (("Current_Ratio",),),
    "PM": (("Profit_Margin",),),
    "RG": (("Revenue_Growth",),),
    "EG": (("Earnings_Growth",),),
    "DY": (("Dividend_Yield_Ratio", "Dividend_Yield"),),
    "EV": (("EV_EBITDA",),),
    "GROSS_NPA": (("Gross_NPA",),),
    "NET_NPA": (("Net_NPA",),),
    "CAPITAL_ADEQUACY": (("Capital_Adequacy",),),
    "SOLVENCY": (("Solvency_Ratio",),),
}

# Components where an absent input would be genuine evidence rather than a data
# gap. Dividend yield is the tempting candidate -- a non-payer has nothing to
# report -- but the feed does not distinguish "pays nothing" from "not
# reported", so treating absence as a zero would penalise a paying company whose
# data is merely missing, which is the exact error this module now fixes. The
# right place to settle it is the collector, by recording an explicit 0.0 when
# the vendor states a company pays no dividend.
FUNDAMENTAL_ABSENCE_IS_ZERO = frozenset()
