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
# Everything a backtest reads from the root other than the panel itself.
SHARED = (
    "bhavcopy",
    "calendar.csv",
    "corporate_actions.csv",
    "security_master.csv",
    "indices.csv",
    "filings_annual.csv",
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

    rows = []
    for record in read_vendor_statements():
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
