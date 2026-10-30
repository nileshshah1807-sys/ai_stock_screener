"""Build ``group_map.csv`` from archived Nifty 500 constituent lists.

Usage::

    python -m tools.build_group_map --root reports_advanced/backtest_ext

Reads ``<root>/nifty500_snapshots/<wayback timestamp>.csv`` (NSE's
``ind_nifty500list.csv`` as the Wayback Machine captured it; fetch one with
``curl https://web.archive.org/web/<timestamp>id_/<original url>``, the
captures listed by
``https://web.archive.org/cdx/search/cdx?url=niftyindices.com/IndexConstituent/ind_nifty500list.csv``
and the same file under ``archives.nseindia.com/content/indices/`` and
``www1.nseindia.com/content/indices/``). Joins each ISIN to the archive's
Security_ID by ISIN core and writes one row per security and capture. See
`backtest.groups`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from backtest.groups import coarse_group
from backtest.security_master import isin_core


def security_ids_by_core(master):
    """ISIN core -> Security_ID, over every ISIN a security has carried."""
    lookup = {}
    for security_id, history in zip(master["Security_ID"], master["ISIN_History"].fillna("")):
        for isin in str(history).split(";"):
            if isin.strip():
                lookup.setdefault(isin_core(isin), str(security_id))
    return lookup


def read_snapshot(path):
    frame = pd.read_csv(path, encoding="utf-8-sig")
    frame.columns = [column.strip() for column in frame.columns]
    stamp = path.stem[:8]
    return pd.DataFrame({
        "ISIN": frame["ISIN Code"].astype(str).str.strip(),
        "Symbol": frame["Symbol"].astype(str).str.strip(),
        "Industry": frame["Industry"].astype(str).str.strip(),
        "Snapshot_Date": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}",
    })


def build(root):
    root = Path(root)
    master = pd.read_csv(root / "security_master.csv")
    lookup = security_ids_by_core(master)
    rows = pd.concat(
        [read_snapshot(path) for path in sorted((root / "nifty500_snapshots").glob("*.csv"))],
        ignore_index=True,
    )
    rows["Group"] = rows["Industry"].map(coarse_group)
    rows["Security_ID"] = rows["ISIN"].map(lambda isin: lookup.get(isin_core(isin)))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="reports_advanced/backtest_ext")
    args = parser.parse_args(argv)
    rows = build(args.root)
    unmatched = rows["Security_ID"].isna()
    print(f"{len(rows)} rows from {rows['Snapshot_Date'].nunique()} captures; "
          f"{int(unmatched.sum())} ISINs not in the security master")
    out = Path(args.root) / "group_map.csv"
    rows[~unmatched].to_csv(out, index=False)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
