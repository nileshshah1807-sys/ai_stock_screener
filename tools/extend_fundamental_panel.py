"""Extend the point-in-time annual panel past the end of the filing archive.

NSE's results endpoint thins out after early 2025, so the panel built from it
(``tools.build_fundamental_panel``) ends at FY2024 and a backtest over any later
date scores on statements that are years stale. This tool writes a *second*
archive root whose panel also carries the fiscal years the filing archive lacks,
taken from the vendor statements the dashboard already stores
(``financial_statements``). The original root is never modified: every recorded
study was run against it, and its rows carry real filing timestamps.

The added rows do not. A vendor statement has a period end and no filing date,
so each is dated at the regulatory deadline -- ``AVAILABILITY_LAG_DAYS`` after
the period end -- which is on or after the true filing for every company that
filed on time. That is conservative for look-ahead and wrong for late filers;
it is also today's restated figure, not the one originally filed. On FY2024,
where both sources exist, the median vendor-to-archive ratio is 1.00 for
revenue, profit and equity (printed on every run).

Only fiscal years the archive panel does not already hold are added, so the
filed figures always win where they exist. NSE only.

The quarterly panel is extended the same way, when the root has one. The
vendor's quarters (about five, the most recent) are appended after the last
filed quarter, each dated ``QUARTER_LAG_DAYS`` after its period end. Growth is
measured against the year-ago quarter, which for the first vendor quarters is a
*filed* figure, so the two sources have to describe the same entity: a company
is stitched only on the basis (consolidated or standalone) whose four filed
quarters of the last archive year sum to the vendor's annual revenue within
``BASIS_TOLERANCE``, and is left out when neither does. The one quarter neither
source carries -- the last of the first vendor fiscal year -- is derived as the
vendor's annual figure less the three filed quarters before it.

Usage::

    python -m tools.extend_fundamental_panel
    python -m tools.extend_fundamental_panel --out reports_advanced/backtest_ext
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.publish_price_series import load_env_file  # noqa: E402

logger = logging.getLogger("extend_panel")

DEFAULT_ROOT = Path("reports_advanced/backtest")
DEFAULT_OUT = Path("reports_advanced/backtest_ext")
# SEBI allows 60 days for annual results; one more so the figure is usable from
# the session after the deadline, matching the archive's availability rule.
AVAILABILITY_LAG_DAYS = 61
# Quarterly results are due in 45 days, and in 60 for the last quarter of the
# year, which is filed with the annual accounts.
QUARTER_LAG_DAYS = 46
# How closely four filed quarters must sum to the vendor's annual revenue for
# the vendor's figures to be treated as the same basis.
BASIS_TOLERANCE = 0.05
# Everything a backtest reads from the root other than the panel itself.
SHARED = (
    "bhavcopy",
    "calendar.csv",
    "corporate_actions.csv",
    "security_master.csv",
    "indices.csv",
    "filings_annual.csv",
    "filings_quarterly.csv",
    "archive_manifest.json",
)


def _value(part, name, index):
    values = ((part or {}).get("rows") or {}).get(name)
    if index is None or not values or index >= len(values) or values[index] is None:
        return np.nan
    return float(values[index])


def _position(part, period):
    periods = (part or {}).get("periods") or []
    return periods.index(period) if period in periods else None


def _ratio(numerator, denominator, *, positive_denominator=False):
    if pd.isna(numerator) or pd.isna(denominator) or denominator == 0:
        return np.nan
    if positive_denominator and denominator <= 0:
        return np.nan
    return numerator / denominator


def vendor_panel_rows(symbol, statements, security_id, isin=""):
    """Panel-shaped annual rows for one stored vendor statement payload."""
    annual = (statements or {}).get("annual") or {}
    income = annual.get("income") or {}
    balance, cashflow = annual.get("balance") or {}, annual.get("cashflow") or {}
    rows = []
    for index, period in enumerate(income.get("periods") or []):
        balance_at, cash_at = _position(balance, period), _position(cashflow, period)
        revenue = _value(income, "revenue", index)
        ebitda = _value(income, "operating_profit", index)
        depreciation = _value(income, "depreciation", index)
        pat, eps = _value(income, "net_profit", index), _value(income, "eps", index)
        pbt, tax = _value(income, "pbt", index), _value(income, "tax", index)
        interest = _value(income, "interest", index)
        ebit = ebitda - depreciation if pd.notna(ebitda) and pd.notna(depreciation) else np.nan
        shares = _ratio(pat, eps)
        available = (
            pd.Timestamp(period) + pd.Timedelta(days=AVAILABILITY_LAG_DAYS)
        ).date().isoformat()
        rows.append(
            {
                "Security_ID": security_id,
                "ISIN": isin,
                "Symbol": symbol,
                "Period_End": period,
                "Fiscal_Year": int(str(period)[:4]),
                "Available_From": available,
                "Filing_Timestamp": f"{available}T00:00:00",
                "Seq_Number": f"VENDOR-{security_id}-{str(period)[:4]}",
                "Is_Consolidated": True,
                "Revenue": revenue,
                "Other_Income": _value(income, "other_income", index),
                "Total_Expenses": _value(income, "expenses", index),
                "Finance_Costs": interest,
                "Depreciation": depreciation,
                "EBIT": ebit,
                "EBITDA": ebitda,
                "PBT": pbt,
                "Tax_Expense": tax,
                "PAT": pat,
                "EPS_Basic": eps,
                "EPS_Diluted": eps,
                "Shares_Outstanding": shares if pd.notna(shares) and shares > 0 else np.nan,
                "Operating_Margin": _ratio(ebit, revenue),
                "Interest_Coverage": _ratio(ebit, interest, positive_denominator=True),
                "Effective_Tax_Rate": _ratio(tax, pbt, positive_denominator=True),
                "OCF": _value(cashflow, "cfo", cash_at),
                "Total_Assets": _value(balance, "total_assets", balance_at),
                "Equity": _value(balance, "shareholders_equity", balance_at),
                "Cash": _value(balance, "cash", balance_at),
                "Total_Debt": _value(balance, "borrowings", balance_at),
                "Has_Balance_Sheet": balance_at is not None,
                "Has_Cash_Flow": cash_at is not None,
            }
        )
    return rows


def extend(panel, vendor):
    """Append vendor rows for the (security, fiscal year) pairs ``panel`` lacks."""
    if vendor.empty:
        return panel.copy(), vendor
    held = set(zip(panel["Security_ID"].astype(str), panel["Fiscal_Year"].astype(int)))
    missing = [
        (str(security), int(year)) not in held
        for security, year in zip(vendor["Security_ID"], vendor["Fiscal_Year"])
    ]
    added = vendor[missing]
    # Only years after the archive's last: an older gap is a company the
    # archive deliberately has no filed figure for, not one to backfill.
    added = added[added["Fiscal_Year"] > int(panel["Fiscal_Year"].max())]
    return pd.concat([panel, added[panel.columns]], ignore_index=True), added


def overlap_report(panel, vendor, fiscal_year):
    """Median vendor/archive ratio per field on a year both sources carry."""
    archive = (
        panel[panel["Fiscal_Year"] == fiscal_year]
        .sort_values("Available_From")
        .drop_duplicates("Security_ID", keep="last")
        .set_index("Security_ID")
    )
    joined = archive.join(
        vendor[vendor["Fiscal_Year"] == fiscal_year].set_index("Security_ID"),
        lsuffix="_archive",
        rsuffix="_vendor",
        how="inner",
    )
    report = {}
    for field in ("Revenue", "PAT", "EBIT", "EPS_Diluted", "Equity", "Total_Debt", "OCF"):
        ratio = (
            (joined[f"{field}_vendor"] / joined[f"{field}_archive"])
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
        )
        if len(ratio):
            report[field] = (
                len(ratio),
                float(ratio.median()),
                float((ratio.sub(1).abs() < 0.05).mean()),
            )
    return report


def _latest_filed(quarters, basis):
    """``{period_end: (revenue, pat)}`` for one basis, newest filing per period."""
    rows = quarters[quarters["_consolidated"] == basis].sort_values("Available_From")
    return {
        period: (revenue, pat)
        for period, revenue, pat in zip(rows["Period_End"], rows["Revenue"], rows["PAT"])
    }


def _year_quarters(year_end):
    """The four quarter ends of the fiscal year ending ``year_end``, oldest first."""
    end = pd.Timestamp(year_end)
    return [
        (end - pd.DateOffset(months=months) + pd.offsets.MonthEnd(0)).date().isoformat()
        for months in (9, 6, 3, 0)
    ]


def vendor_basis(filed, annual_revenue, year_end, *, tolerance=BASIS_TOLERANCE):
    """Which filed basis the vendor's annual figure matches: True, False or None.

    ``filed`` holds one security's filed quarters. Consolidated is tried first
    because it is what the vendor normally reports.
    """
    if pd.isna(annual_revenue) or annual_revenue <= 0 or filed.empty:
        return None
    for basis in (True, False):
        by_period = _latest_filed(filed, basis)
        revenues = [by_period.get(period, (np.nan, np.nan))[0] for period in _year_quarters(year_end)]
        if any(pd.isna(value) for value in revenues):
            continue
        if abs(sum(revenues) / annual_revenue - 1.0) <= tolerance:
            return basis
    return None


def vendor_quarter_rows(symbol, statements, security_id, filed, last_filed_year_end):
    """Quarter rows for one security past the filed archive, or ``[]``.

    ``filed`` is that security's filed quarters (may be empty) and
    ``last_filed_year_end`` the last fiscal year end the archive covers fully.
    """
    annual = ((statements or {}).get("annual") or {}).get("income") or {}
    quarterly = ((statements or {}).get("quarterly") or {}).get("income") or {}
    periods = quarterly.get("periods") or []
    if not periods:
        return []
    basis = vendor_basis(
        filed,
        _value(annual, "revenue", _position(annual, last_filed_year_end)),
        last_filed_year_end,
    )
    if basis is None:
        return []
    by_period = _latest_filed(filed, basis)

    def row(period, revenue, pat, lag):
        available = (pd.Timestamp(period) + pd.Timedelta(days=lag)).date().isoformat()
        return {
            "Security_ID": security_id,
            "ISIN": "",
            "Symbol": symbol,
            "Period_End": period,
            "Available_From": available,
            "Filing_Timestamp": f"{available}T00:00:00",
            "Seq_Number": f"VENDOR-{security_id}-{period}",
            "Is_Consolidated": basis,
            "Revenue": revenue,
            "Other_Income": np.nan,
            "PBT": np.nan,
            "PAT": pat,
            "EPS_Basic": np.nan,
            "EPS_Diluted": np.nan,
        }

    rows = []
    # The year after the archive's last: three filed quarters, then one that
    # neither source reports directly.
    next_year_end = (pd.Timestamp(last_filed_year_end) + pd.DateOffset(years=1)).date().isoformat()
    first_three = _year_quarters(next_year_end)[:3]
    filed_three = [by_period.get(period) for period in first_three]
    at = _position(annual, next_year_end)
    if (
        next_year_end not in by_period
        and next_year_end not in periods
        and at is not None
        and all(item is not None for item in filed_three)
    ):
        revenue = _value(annual, "revenue", at) - sum(item[0] for item in filed_three)
        pat = _value(annual, "net_profit", at) - sum(item[1] for item in filed_three)
        # A non-positive residual means the year and its quarters disagree.
        if pd.notna(revenue) and revenue > 0:
            rows.append(row(next_year_end, revenue, pat, AVAILABILITY_LAG_DAYS))

    for index, period in enumerate(periods):
        if period in by_period:
            continue
        year_end_quarter = pd.Timestamp(period).month == pd.Timestamp(last_filed_year_end).month
        rows.append(
            row(
                period,
                _value(quarterly, "revenue", index),
                _value(quarterly, "net_profit", index),
                AVAILABILITY_LAG_DAYS if year_end_quarter else QUARTER_LAG_DAYS,
            )
        )
    return rows


def extend_quarters(quarter_panel, records, security_of):
    """Append vendor quarters to the filed quarterly panel."""
    working = quarter_panel.copy()
    working["_consolidated"] = working["Is_Consolidated"].astype(str).str.lower().isin({"true", "1"})
    for column in ("Revenue", "PAT"):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    ends = pd.to_datetime(working["Period_End"], errors="coerce")
    # The last fiscal year the archive covers in full: its year end is filed.
    year_ends = ends[ends.dt.month == 3]
    last_filed_year_end = year_ends.max().date().isoformat()
    filed_by_security = {str(key): group for key, group in working.groupby("Security_ID")}
    empty = working.iloc[0:0]

    rows, stitched, skipped = [], 0, 0
    for record in records:
        security_id = security_of.get(record["symbol"])
        if security_id is None or not record.get("has_data"):
            continue
        added = vendor_quarter_rows(
            record["symbol"],
            record["statements"],
            security_id,
            filed_by_security.get(str(security_id), empty),
            last_filed_year_end,
        )
        if added:
            stitched += 1
            rows.extend(added)
        else:
            skipped += 1
    vendor = pd.DataFrame(rows, columns=list(quarter_panel.columns))
    return pd.concat([quarter_panel, vendor], ignore_index=True), vendor, stitched, skipped


def read_vendor_statements():
    from storage.dashboard_repository import DashboardRepository

    load_env_file()
    repository = DashboardRepository.from_environment("NSE")
    return repository._paged(
        "financial_statements",
        repository._scoped({"select": "symbol,statements,has_data", "order": "symbol.asc"}),
        # Each row carries four years of three statements; small pages keep a
        # response inside the read timeout on a slow link.
        page=100,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    root, out = Path(args.root).resolve(), Path(args.out)
    panel = pd.read_csv(root / "fundamental_panel.csv", dtype={"ISIN": str, "Seq_Number": str})
    master = pd.read_csv(root / "security_master.csv", dtype=str)
    # A reused ticker maps to several securities; the one still trading is the
    # company the vendor reports under that symbol today.
    master = master.sort_values("Last_Session")
    security_of = dict(zip(master["Current_Symbol"], master["Security_ID"]))
    isin_of = dict(zip(master["Security_ID"], master["ISIN"]))

    records = read_vendor_statements()
    rows = []
    for record in records:
        security_id = security_of.get(record["symbol"])
        if security_id is None or not record.get("has_data"):
            continue
        rows.extend(
            vendor_panel_rows(
                record["symbol"], record["statements"], security_id, isin_of.get(security_id, "")
            )
        )
    vendor = pd.DataFrame(rows)
    logger.info("Vendor statements: %d rows, %d securities", len(vendor), vendor["Security_ID"].nunique())

    last_archive_year = int(panel["Fiscal_Year"].max())
    for field, (count, median, within) in overlap_report(panel, vendor, last_archive_year).items():
        logger.info(
            "  FY%d %-12s n=%d  median vendor/archive %.3f  within 5%%: %.0f%%",
            last_archive_year, field, count, median, within * 100,
        )

    extended, added = extend(panel, vendor)
    out.mkdir(parents=True, exist_ok=True)
    for name in SHARED:
        link = out / name
        if (root / name).exists() and not link.exists():
            os.symlink(root / name, link)
    extended.to_csv(out / "fundamental_panel.csv", index=False)

    quarter_path = root / "quarterly_panel.csv"
    if quarter_path.exists():
        quarter_panel = pd.read_csv(quarter_path, dtype={"ISIN": str, "Seq_Number": str})
        quarters, vendor_quarters, stitched, skipped = extend_quarters(
            quarter_panel, records, security_of
        )
        target = out / "quarterly_panel.csv"
        if target.is_symlink():
            target.unlink()
        quarters.to_csv(target, index=False)
        logger.info(
            "Quarterly panel: %d rows (%d added for %d securities; %d left out, "
            "no filed basis matched the vendor's annual revenue) -> %s",
            len(quarters), len(vendor_quarters), stitched, skipped, target,
        )
        if len(vendor_quarters):
            logger.info(
                "  added by quarter: %s",
                vendor_quarters.groupby("Period_End").size().to_dict(),
            )
    logger.info(
        "Extended panel: %d rows (%d added: %s) -> %s",
        len(extended),
        len(added),
        added.groupby("Fiscal_Year").size().to_dict() if len(added) else {},
        out / "fundamental_panel.csv",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
