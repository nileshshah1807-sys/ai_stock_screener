"""Generic fundamental scoring.

Component capacity and coverage, sector-relative percentile scores, per-row
model selection, and the generic fundamental score itself.
"""

import numpy as np
import pandas as pd

from ..numeric import safe_float
from .constants import (
    FUNDAMENTAL_ABSENCE_IS_ZERO,
    FUNDAMENTAL_COMPONENT_INPUTS,
    FUNDAMENTAL_COMPONENT_MAX,
    SECTOR_RELATIVE_COLUMN_BY_KEY,
    SECTOR_RELATIVE_FIELDS,
    SECTOR_RELATIVE_MINIMUMS,
)
from .points import (
    _financial_quality_percentages,
    _growth_points,
    _pe_points,
    _profit_points,
    _roa_points,
    _roe_points,
)


def fundamental_component_capacity(fundamental_model):
    """Point capacity per component for the given fundamental model."""

    return FUNDAMENTAL_COMPONENT_MAX.get(
        fundamental_model, FUNDAMENTAL_COMPONENT_MAX["Generic Fundamental Model"]
    )


def fundamental_score_details(row, fundamental_model, components):
    """Coverage-normalised fundamental score.

    Mirrors ``technical_score_details``: unobservable components leave both the
    numerator and the denominator, and the resulting observed score is shrunk
    toward neutral 50 by how much of the model was actually measurable. Absent
    evidence therefore lowers confidence instead of asserting the worst value.
    """

    capacity = fundamental_component_capacity(fundamental_model)
    observed_capacity = 0.0
    observed_points = 0.0
    missing = []
    for key, component_max in capacity.items():
        if _fundamental_component_observed(row, key):
            observed_capacity += float(component_max)
            observed_points += float(components.get(key) or 0.0)
        else:
            missing.append(key)

    total_capacity = float(sum(capacity.values())) or 1.0
    coverage = observed_capacity / total_capacity
    if observed_capacity <= 0:
        observed_score = 50.0
    else:
        observed_score = max(
            0.0, min(100.0, observed_points / observed_capacity * 100.0)
        )
    adjusted_score = 50.0 + coverage * (observed_score - 50.0)
    return {
        "points": observed_points,
        "observed_capacity": observed_capacity,
        "total_capacity": total_capacity,
        "coverage": coverage,
        "observed_score": observed_score,
        "adjusted_score": max(0.0, min(100.0, adjusted_score)),
        "missing_components": missing,
    }


def _fundamental_component_observed(row, key):
    if key in FUNDAMENTAL_ABSENCE_IS_ZERO:
        return True
    requirements = FUNDAMENTAL_COMPONENT_INPUTS.get(key)
    if not requirements:
        return True
    # requirements is an AND of groups, each group an OR of interchangeable
    # columns: every group needs at least one reported input.
    return all(
        any(safe_float(row.get(column)) is not None for column in alternatives)
        for alternatives in requirements
    )


def sector_relative_fund_scores(
    merged_df, min_peers=5, *, reference_eligible=None
):
    """Percentile-rank each fundamental metric against same-sector peers in the
    current scan, instead of a single fixed absolute threshold.

    A PE of 18 might be cheap for an IT stock but expensive for a Utility - this
    compares each stock to the other same-sector names actually being scored
    today rather than one universal bar. Returns a DataFrame (same index as
    merged_df) of per-column scores already expressed on that column's normal
    point scale (see SECTOR_RELATIVE_FIELDS); cells are NaN wherever the stock's
    own value is missing or its sector has fewer than ``min_peers`` members, so
    the caller can fall back to the absolute-threshold score for those cases.
    ``reference_eligible`` can exclude stale, unavailable, or anomalous records
    from both the reference distribution and relative scoring without removing
    those stocks from the broader model.
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
    if reference_eligible is None:
        reference_eligible = pd.Series(True, index=merged_df.index, dtype=bool)
    elif isinstance(reference_eligible, pd.Series):
        reference_eligible = reference_eligible.reindex(merged_df.index).fillna(False)
    else:
        reference_eligible = pd.Series(
            reference_eligible, index=merged_df.index, dtype=bool
        )
    reference_eligible = reference_eligible.astype(bool) & valid_sector

    out = pd.DataFrame(index=merged_df.index)
    for column, (_, max_pts, higher_is_better) in SECTOR_RELATIVE_FIELDS.items():
        if column not in merged_df:
            out[column] = np.nan
            continue
        values = pd.to_numeric(merged_df[column], errors="coerce")
        if column in SECTOR_RELATIVE_MINIMUMS:
            minimum = SECTOR_RELATIVE_MINIMUMS[column]
            if column in {"PE_Ratio", "PB_Ratio", "EV_EBITDA"}:
                values = values.where(values > minimum)
            else:
                values = values.where(values >= minimum)
        reference_values = values.where(reference_eligible)
        group_size = reference_values.groupby(sector).transform("count")
        raw_rank = reference_values.groupby(sector).rank(method="average")
        # Map every peer group symmetrically onto [0, 1]. pandas rank(pct=True)
        # maps ranks to [1/n, 1], so inverting it gives lower-is-better metrics
        # [0, (n-1)/n] and unfairly prevents the best value from scoring full
        # points. The explicit (rank - 1) / (n - 1) transform avoids that bias.
        pct_rank = (raw_rank - 1.0) / (group_size - 1.0)
        if not higher_is_better:
            pct_rank = 1.0 - pct_rank
        score = pct_rank * max_pts
        score = score.where(
            (group_size >= min_peers) & valid_sector & reference_eligible
        )
        out[column] = score
    return out


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
    s = safe_float
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
    s = safe_float
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
    s = safe_float
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
    if de is None or de < 0: scores["DE"] = 0
    elif de < 30: scores["DE"] = 10
    elif de < 70: scores["DE"] = 8
    elif de < 150: scores["DE"] = 5
    else: scores["DE"] = 2

    cr = s(row.get("Current_Ratio"))
    if cr is None or cr < 0: scores["CR"] = 0
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

    dy = s(
        row.get("Dividend_Yield_Ratio")
        if row.get("Dividend_Yield_Ratio") is not None
        else row.get("Dividend_Yield")
    )
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
        weight = max(0.0, min(1.0, safe_float(sector_relative_weight, 0.5) or 0.0))
        if weight > 0:
            for key, column in SECTOR_RELATIVE_COLUMN_BY_KEY.items():
                sector_score = sector_relative.get(column) if hasattr(sector_relative, "get") else None
                if sector_score is None or (isinstance(sector_score, float) and pd.isna(sector_score)):
                    continue
                scores[key] = round(scores[key] * (1 - weight) + sector_score * weight, 2)

    # Invalid valuation/domain observations remain zero even if an older cache
    # or external caller supplies a peer score for them.
    if pe is not None and pe <= 0:
        scores["PE"] = 0.0
    if pb is not None and pb <= 0:
        scores["PB"] = 0.0
    if ev is not None and ev <= 0:
        scores["EV"] = 0.0
    if de is not None and de < 0:
        scores["DE"] = 0.0
    if cr is not None and cr < 0:
        scores["CR"] = 0.0

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
