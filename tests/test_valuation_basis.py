"""The live ratios on screen and the scored ratios are one arithmetic.

The evening run works P/E, P/B, market cap, EV/EBITDA and the yield out at
the close (`screener.valuation_basis.price_ratios`); the dashboard reads them
at the live price from the ``live_valuation`` view. Here the view's own SQL
runs on SQLite over the basis the publisher would write from the scored row,
at the close, and must give the scored figures back.
"""

import re
import sqlite3
import unittest
from pathlib import Path

import pandas as pd

from screener.data_collection import align_valuation_to_completed_price_bar
from screener.valuation_basis import attach_basis
from workers.dashboard_publisher import CoercionReport, basis_row

SCHEMA = Path(__file__).resolve().parents[1] / "storage" / "valuation_basis_schema.sql"

LIVE_QUOTES = """create table live_quotes (
    market text, symbol text, kind text, price real, change_pct real,
    volume integer, traded_at text, session text, fetched_at text)"""
BASIS = """create table valuation_basis (
    market text, symbol text, shares_outstanding real, net_profit_ttm real,
    book_equity real, ebitda_ttm real, revenue_ttm real, total_debt real,
    total_cash real, dividend_per_share real, period_end text,
    statement_basis text, source text, run_date text, updated_at text)"""


def view_sql():
    text = SCHEMA.read_text(encoding="utf-8")
    return re.search(r"create or replace view live_valuation .*? as\n(with .*?;)", text, re.S).group(1)


def scored(**overrides):
    row = {
        "Symbol": "AAA",
        "Current_Price": 870.0,
        "EPS": 15.5,
        "Book_Value": 120.0,
        "Shares_Outstanding": 48.8e7,
        "EBITDA": 1.6e10,
        "Total_Debt": 4.0e9,
        "Total_Cash": 1.5e9,
        "Dividend_Rate": 2.0,
        "Fundamental_Source": "Yahoo Finance quote metadata",
        **overrides,
    }
    return attach_basis(align_valuation_to_completed_price_bar(pd.DataFrame([row]))).iloc[0]


def live(record, *, price, change_pct=1.0):
    db = sqlite3.connect(":memory:")
    db.execute(LIVE_QUOTES)
    db.execute(BASIS)
    db.execute(
        "insert into live_quotes values ('NSE', 'AAA', 'stock', ?, ?, 1, 't', 's', 'f')",
        (price, change_pct),
    )
    row = basis_row(record.to_dict(), "2026-10-23", CoercionReport())
    if row is not None:
        columns = ["market", *row]
        db.execute(
            f"insert into valuation_basis ({','.join(columns)}) values ({','.join('?' * len(columns))})",
            ["NSE", *row.values()],
        )
    cursor = db.execute(view_sql().rstrip(";"))
    names = [column[0] for column in cursor.description]
    return dict(zip(names, cursor.fetchone(), strict=True))


class ParityTests(unittest.TestCase):
    def test_at_the_close_the_view_gives_the_scored_ratios_back(self):
        record = scored()
        view = live(record, price=record["Current_Price"])
        for metric, column in (
            ("PE_Ratio", "pe_ratio"),
            ("PB_Ratio", "pb_ratio"),
            ("Market_Cap", "market_cap"),
            ("EV_EBITDA", "ev_ebitda"),
            ("Dividend_Yield", "dividend_yield"),
        ):
            with self.subTest(metric=metric):
                self.assertAlmostEqual(view[column], record[metric], places=6)

    def test_a_loss_has_a_negative_pe_in_both(self):
        record = scored(EPS=-4.0)
        self.assertLess(record["PE_Ratio"], 0)
        view = live(record, price=record["Current_Price"])
        self.assertAlmostEqual(view["pe_ratio"], record["PE_Ratio"], places=6)

    def test_the_ratios_move_with_the_live_price(self):
        record = scored()
        view = live(record, price=record["Current_Price"] * 1.05)
        self.assertAlmostEqual(view["pe_ratio"], record["PE_Ratio"] * 1.05, places=6)
        self.assertAlmostEqual(view["market_cap"], record["Market_Cap"] * 1.05, places=0)

    def test_a_change_of_unit_has_no_ratios(self):
        # A split on its ex-date: the new price over the old share count.
        view = live(scored(), price=435.0, change_pct=None)
        self.assertEqual(view["price"], 435.0)
        self.assertIsNone(view["pe_ratio"])
        self.assertIsNone(view["market_cap"])
        self.assertIsNone(view["dividend_yield"])

    def test_a_stock_with_no_basis_still_has_its_quote(self):
        view = live(scored(EPS=None, Book_Value=None, Shares_Outstanding=None, EBITDA=None), price=10.0)
        self.assertEqual(view["price"], 10.0)
        self.assertIsNone(view["pe_ratio"])


class BasisRowTests(unittest.TestCase):
    def test_the_vendor_row_names_its_source(self):
        row = basis_row(scored().to_dict(), "2026-10-23", CoercionReport())
        self.assertEqual(row["source"], "Yahoo Finance quote metadata")
        self.assertAlmostEqual(row["net_profit_ttm"], 15.5 * 48.8e7, places=0)
        self.assertEqual(row["run_date"], "2026-10-23")

    def test_nothing_to_divide_by_writes_no_row(self):
        record = scored(EPS=None, Book_Value=None, Shares_Outstanding=None, EBITDA=None)
        self.assertIsNone(basis_row(record.to_dict(), "2026-10-23", CoercionReport()))


if __name__ == "__main__":
    unittest.main()
