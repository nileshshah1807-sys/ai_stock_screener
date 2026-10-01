"""Compare EDGAR-derived statement factors with Yahoo's, symbol by symbol.

The factor model was validated on Yahoo's statements. Before EDGAR replaces
them for US filers, this measures how far the two disagree on every derived
column, using the same ``derive_statement_factors`` arithmetic for both, so a
difference is a difference in the source numbers and nothing else.

Usage::

    SEC_USER_AGENT="Name contact@example.com" \\
        python -m tools.compare_statement_sources AAPL MSFT JPM
    python -m tools.compare_statement_sources --file symbols.txt --csv out.csv

Per column it prints how many symbols each source covers, the median relative
difference where both report, and the share agreeing within 5%.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np
import pandas as pd
import yfinance as yf

from screener.edgar import EdgarClient
from screener.statements import DERIVED_COLUMNS, derive_statement_factors

TEXT_COLUMNS = {
    "Statement_Latest_Period",
    "Statement_Free_Cash_Flow_Source",
    "Statement_Negative_Base_Flags",
}
TOLERANCE = 0.05


def _yahoo(symbol):
    ticker = yf.Ticker(symbol.replace(".", "-"))
    return derive_statement_factors(ticker.income_stmt, ticker.balance_sheet, ticker.cashflow)


def _edgar(client, symbol):
    frames = client.annual_frames(symbol)
    return derive_statement_factors(*frames) if frames else None


def compare(symbols, client, *, pause=1.5):
    rows = []
    for symbol in symbols:
        try:
            edgar = _edgar(client, symbol)
        except Exception as exc:
            print(f"{symbol}: EDGAR failed: {exc}", file=sys.stderr)
            edgar = None
        try:
            yahoo = _yahoo(symbol)
        except Exception as exc:
            print(f"{symbol}: Yahoo failed: {exc}", file=sys.stderr)
            yahoo = None
        time.sleep(pause)
        for column in DERIVED_COLUMNS:
            rows.append({
                "Symbol": symbol,
                "Column": column,
                "EDGAR": None if edgar is None else edgar.get(column),
                "Yahoo": None if yahoo is None else yahoo.get(column),
            })
    return pd.DataFrame(rows)


def summarise(long):
    lines = []
    for column in DERIVED_COLUMNS:
        part = long[long["Column"] == column]
        if column in TEXT_COLUMNS:
            both = part.dropna(subset=["EDGAR", "Yahoo"])
            same = (both["EDGAR"].astype(str) == both["Yahoo"].astype(str)).mean() if len(both) else np.nan
            lines.append((column, len(both), part["Yahoo"].notna().sum(), part["EDGAR"].notna().sum(), np.nan, same))
            continue
        edgar = pd.to_numeric(part["EDGAR"], errors="coerce")
        yahoo = pd.to_numeric(part["Yahoo"], errors="coerce")
        both = edgar.notna() & yahoo.notna()
        scale = yahoo[both].abs().where(yahoo[both].abs() > 1e-9)
        relative = ((edgar[both] - yahoo[both]).abs() / scale).dropna()
        lines.append((
            column,
            int(both.sum()),
            int(yahoo.notna().sum()),
            int(edgar.notna().sum()),
            float(relative.median()) if len(relative) else np.nan,
            float((relative <= TOLERANCE).mean()) if len(relative) else np.nan,
        ))
    return pd.DataFrame(
        lines, columns=["Column", "Both", "Yahoo", "EDGAR", "Median_Rel_Diff", "Within_5pct"]
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("symbols", nargs="*")
    parser.add_argument("--file", help="one symbol per line")
    parser.add_argument("--csv", help="write the per-symbol comparison here")
    args = parser.parse_args(argv)
    symbols = list(args.symbols)
    if args.file:
        with open(args.file, encoding="utf-8") as handle:
            symbols += [line.strip() for line in handle if line.strip()]
    if not symbols:
        parser.error("give symbols or --file")

    client = EdgarClient(os.environ.get("SEC_USER_AGENT", ""))
    long = compare(symbols, client)
    if args.csv:
        long.to_csv(args.csv, index=False)
    covered = long[long["Column"] == "Statement_Years"]
    print(f"Symbols: {len(symbols)}  EDGAR served: {covered['EDGAR'].notna().sum()}  "
          f"Yahoo served: {covered['Yahoo'].notna().sum()}")
    with pd.option_context("display.width", 160, "display.max_rows", 100):
        print(summarise(long).to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
