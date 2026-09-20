"""Per-metric point curves.

Small independent curves (PE, ROE, growth, ...) shared by the generic
fundamental model and the sector-specific models.
"""

from ..numeric import safe_float


def _financial_quality_percentages(row):
    """Normalize NPA/CAR fields using capital adequacy to infer row units."""
    s = safe_float
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
