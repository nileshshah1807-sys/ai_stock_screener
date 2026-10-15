"""Compare filing-derived quarter growth with the vendor's, symbol by symbol.

The model's two quarterly inputs were read from Yahoo's quote metadata. Before
NSE's results filings replace them, this measures two things:

* **agreement** -- where both sources describe the same quarter, how far the
  two growth rates differ;
* **freshness** -- for how many companies the filings already carry a later
  quarter than the vendor does.

Usage::

    python -m tools.compare_quarter_growth_sources SYMBOL [SYMBOL ...]
    python -m tools.compare_quarter_growth_sources --sample 150 --csv out.csv
    python -m tools.compare_quarter_growth_sources --file symbols.txt

``--sample`` draws from the market's safety-net names plus a seeded random
draw of the companies in the filing index, so a run is repeatable.

The filings side is read from the ``quarterly_filings`` table, as the
screener reads it, so ``SUPABASE_URL`` and ``SUPABASE_SERVICE_ROLE_KEY`` must
be set.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from screener import quarterly_results
from screener.markets import NSE, resolve, ticker_for

# Percentage points. Two sources rounding the same filing differ by less.
TOLERANCE = 0.02
FIELDS = (
    ("Revenue_Growth", "revenueGrowth"),
    ("Earnings_Growth", "earningsGrowth"),
    # The vendor's other earnings figure: net income rather than EPS, which
    # is the definition the filings side uses.
    ("Earnings_Growth", "earningsQuarterlyGrowth"),
)


def filing_growth(symbols, *, today):
    config = SimpleNamespace(
        QUARTERLY_RESULTS_FILINGS_ENABLED=True,
        SUPABASE_URL=os.getenv("SUPABASE_URL", ""),
        SUPABASE_SERVICE_ROLE_KEY=os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
        SUPABASE_READ_ONLY=True,
    )
    collector = quarterly_results.QuarterlyResultsCollector(
        config,
        provider="nse_integrated_filings",
        clock=lambda: datetime.combine(today, datetime.min.time()),
    )
    growth = collector.collect(symbols)
    return growth.set_index("Symbol"), collector.diagnostics


def vendor_growth(symbols, profile, *, per_minute=40):
    import yfinance as yf

    rows = {}
    window_start, in_window = time.time(), 0
    for symbol in symbols:
        in_window += 1
        if in_window >= per_minute:
            elapsed = time.time() - window_start
            if elapsed < 60:
                time.sleep(62 - elapsed)
            window_start, in_window = time.time(), 0
        try:
            info = yf.Ticker(ticker_for(symbol, profile)).info or {}
        except Exception as exc:
            print(f"{symbol}: vendor failed: {exc}", file=sys.stderr)
            continue
        quarter = info.get("mostRecentQuarter")
        rows[symbol] = {
            "Vendor_Quarter": (
                datetime.fromtimestamp(quarter, UTC).date().isoformat()
                if quarter
                else None
            ),
            **{f"Vendor_{key}": info.get(key) for _, key in FIELDS},
        }
    return pd.DataFrame.from_dict(rows, orient="index")


def sample_symbols(count, profile, *, today, seed=7):
    index = quarterly_results.fetch_index(today - timedelta(days=600), today)
    listed = sorted(set(index["Symbol"]))
    anchors = [s for s in profile.safety_net_symbols if s in set(listed)]
    rest = [s for s in listed if s not in set(anchors)]
    random.Random(seed).shuffle(rest)
    return (anchors + rest)[:count]


def summarise(table):
    filed_quarter = table["Quarter_Period_End"]
    vendor_quarter = table["Vendor_Quarter"]
    same = table[filed_quarter == vendor_quarter]
    newer = table[
        filed_quarter.notna()
        & (vendor_quarter.isna() | (filed_quarter > vendor_quarter))
    ]
    older = table[
        filed_quarter.notna() & vendor_quarter.notna() & (filed_quarter < vendor_quarter)
    ]
    print(f"symbols compared            : {len(table)}")
    print(f"served by filings           : {int(filed_quarter.notna().sum())}")
    print(f"same quarter in both        : {len(same)}")
    print(f"filings on a later quarter  : {len(newer)}")
    print(f"vendor on a later quarter   : {len(older)}")
    print()
    print(f"{'filings vs vendor field':<44}{'both':>6}{'median |diff|':>15}{'within 2pp':>12}")
    for column, key in FIELDS:
        label = f"{column} vs {key}"
        filed = pd.to_numeric(same[column], errors="coerce")
        vendor = pd.to_numeric(same[f"Vendor_{key}"], errors="coerce")
        both = filed.notna() & vendor.notna()
        if not both.any():
            print(f"{label:<44}{0:>6}")
            continue
        gap = (filed[both] - vendor[both]).abs()
        print(
            f"{label:<44}{int(both.sum()):>6}"
            f"{float(np.median(gap)) * 100:>13.2f}pp"
            f"{float((gap <= TOLERANCE).mean()) * 100:>11.0f}%"
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("symbols", nargs="*")
    parser.add_argument("--file", help="one symbol per line")
    parser.add_argument("--sample", type=int, help="draw this many symbols")
    parser.add_argument("--csv", help="write the per-symbol table here")
    args = parser.parse_args(argv)

    profile = resolve(NSE)
    today = date.today()
    symbols = [s.strip().upper() for s in args.symbols if s.strip()]
    if args.file:
        symbols += [
            line.strip().upper()
            for line in Path(args.file).read_text().splitlines()
            if line.strip()
        ]
    if args.sample:
        symbols += sample_symbols(args.sample, profile, today=today)
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        parser.error("name some symbols, or pass --file or --sample")

    filed, diagnostics = filing_growth(symbols, today=today)
    print(f"filings: {diagnostics}")
    vendor = vendor_growth(symbols, profile)
    table = pd.DataFrame(index=pd.Index(symbols, name="Symbol")).join(filed).join(vendor)
    summarise(table)
    if args.csv:
        table.to_csv(args.csv)
        print(f"\nper-symbol table -> {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
