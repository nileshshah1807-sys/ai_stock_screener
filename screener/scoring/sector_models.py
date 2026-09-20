"""Sector-specific fundamental models.

Financial services (banks, NBFCs, insurers, capital markets) and real estate
score on different evidence from the generic model, so they carry their own
point curves rather than being forced through the generic one.
"""

from ..numeric import safe_float
from .fundamental import fundamental_model_for_row
from .points import (
    _bank_risk_points,
    _dividend_points,
    _growth_points,
    _pb_roe_points,
    _pe_points,
    _profit_points,
    _roa_points,
    _roe_points,
)


def score_financial_services(row, fundamental_model=None, return_components=False):
    """Industry-specific equity models; never use debt as a bank quality input."""
    s = safe_float
    model = fundamental_model or fundamental_model_for_row(row)
    pe = s(row.get("PE_Ratio"))
    pb = s(row.get("PB_Ratio"))
    roe = s(row.get("ROE"))
    roa = s(row.get("ROA"))
    margin = s(row.get("Profit_Margin"))
    revenue_growth = s(row.get("Revenue_Growth"))
    earnings_growth = s(row.get("Earnings_Growth"))
    dividend_yield = s(
        row.get("Dividend_Yield_Ratio")
        if row.get("Dividend_Yield_Ratio") is not None
        else row.get("Dividend_Yield")
    )

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
    s = safe_float
    scores = {}

    pe = s(row.get("PE_Ratio"))
    scores["PE"] = _pe_points(pe, 15)

    pb = s(row.get("PB_Ratio"))
    roe = s(row.get("ROE"))
    scores["PB_ROE"] = _pb_roe_points(pb, roe, 15)

    debt_to_equity = s(row.get("Debt_to_Equity"))
    scores["DE"] = 0 if debt_to_equity is None or debt_to_equity < 0 else 15 if debt_to_equity < 30 else 12 if debt_to_equity < 70 else 7 if debt_to_equity < 120 else 3

    current_ratio = s(row.get("Current_Ratio"))
    scores["CR"] = 0 if current_ratio is None or current_ratio < 0 else 10 if current_ratio >= 1.5 else 7 if current_ratio >= 1.0 else 3

    margin = s(row.get("Profit_Margin"))
    scores["PM"] = _profit_points(margin, 15)

    revenue_growth = s(row.get("Revenue_Growth"))
    scores["RG"] = _growth_points(revenue_growth, 15)

    earnings_growth = s(row.get("Earnings_Growth"))
    scores["EG"] = _growth_points(earnings_growth, 15)
    return scores if return_components else sum(scores.values())
