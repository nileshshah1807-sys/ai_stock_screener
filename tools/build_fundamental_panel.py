"""Build the point-in-time annual fundamental panel from cached XBRL.

Assembles, in the only order that preserves point-in-time discipline:

1. filing metadata (what was filed, and when it was broadcast)
2. **availability** -- the next completed session after broadcast, which is the
   single gate deciding what a past decision could see
3. identity -- ISIN resolved to the bridged ``Security_ID`` so a pre-split filing
   joins to the same company as a post-split price
4. parsed XBRL facts
5. one row per security and fiscal year

Step 2 is not optional and is not implied by the filing date. ``FilingStore``
deliberately writes ``Available_From`` empty because it has no calendar; leaving
it empty makes every point-in-time query silently return nothing, so this tool
fails loudly if the column is still blank after the step runs.

Usage::

    python -m tools.build_fundamental_panel
    python -m tools.build_fundamental_panel --workers 12
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import logging
from pathlib import Path
import sys
import time

import pandas as pd

logger = logging.getLogger("panel")

DEFAULT_ROOT = Path("reports_advanced/backtest")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    from backtest.calendar import CalendarLedger, TradingCalendar
    from backtest.bhavcopy import BhavcopyStore
    from backtest.filings import attach_availability
    from backtest.security_master import SecurityMaster
    from backtest.xbrl import (
        build_panel,
        coverage_summary,
        deduplicate_panel,
    )
    from tools.backfill_xbrl import document_path

    root = Path(args.root)

    # --- calendar -------------------------------------------------------
    ledger = CalendarLedger(root / "calendar.csv")
    sessions = set(ledger.sessions()) | set(BhavcopyStore(root / "bhavcopy").cached_dates())
    if not sessions:
        raise SystemExit("No trading sessions cached; run the archive backfill first")
    calendar = TradingCalendar(sorted(sessions))
    logger.info(
        "Calendar: %d sessions, %s -> %s",
        len(calendar),
        calendar.sessions[0],
        calendar.sessions[-1],
    )

    # --- master ---------------------------------------------------------
    master = SecurityMaster.load(root / "security_master.csv")
    logger.info("Security master: %d securities", len(master))

    # --- filings + availability ------------------------------------------
    filings_path = root / "filings_annual.csv"
    if not filings_path.exists():
        raise SystemExit(f"No filing metadata at {filings_path}")
    filings = pd.read_csv(
        filings_path, dtype={"ISIN": str, "Seq_Number": str}
    )
    logger.info("Filings: %d rows", len(filings))

    filings = attach_availability(filings, calendar)
    resolved = filings["Available_From"].astype(str).str.len().gt(0)
    logger.info(
        "Availability resolved for %d of %d filings (%.1f%%)",
        int(resolved.sum()),
        len(filings),
        100.0 * resolved.mean(),
    )
    if not resolved.any():
        raise SystemExit(
            "Available_From is empty for every filing. Point-in-time selection "
            "would return nothing; check that the calendar spans the filing dates."
        )
    filings = filings.loc[resolved].reset_index(drop=True)

    # --- identity --------------------------------------------------------
    # ISIN first; a filing under a pre-split ISIN must land on the same
    # Security_ID as the post-split price series, which the master bridges.
    security_ids = []
    unresolved = 0
    for isin, symbol, available in zip(
        filings["ISIN"].astype(str),
        filings["Symbol"].astype(str),
        filings["Available_From"].astype(str),
    ):
        resolved_id = master.security_id_for_isin(isin)
        if not resolved_id:
            # Placeholder ISINs exist (IN0000000000). Fall back to a dated symbol
            # lookup, which is safe because it is resolved as of a known date.
            try:
                resolved_id = master.resolve_symbol(symbol, available)
            except Exception:
                resolved_id = None
        if not resolved_id:
            unresolved += 1
        security_ids.append(resolved_id)
    filings["Security_ID"] = security_ids
    logger.info(
        "Identity: %d filings could not be mapped to a security (%.1f%%)",
        unresolved,
        100.0 * unresolved / max(1, len(filings)),
    )
    filings = filings[filings["Security_ID"].notna()].reset_index(drop=True)

    filings["Is_Consolidated"] = (
        filings.get("Consolidated", pd.Series(False, index=filings.index))
        .fillna(False)
        .astype(bool)
    )

    # --- parse ------------------------------------------------------------
    started = time.monotonic()

    def on_progress(done, total, kept):
        logger.info("  parsed %d/%d, %d usable rows", done, total, kept)

    panel = build_panel(
        filings,
        lambda seq, period: document_path(root, seq, period),
        workers=args.workers,
        on_progress=on_progress,
    )
    logger.info(
        "Parsed %d rows in %.1fs", len(panel), time.monotonic() - started
    )
    if panel.empty:
        raise SystemExit("Parsed zero usable rows; check the XBRL cache")

    deduped = deduplicate_panel(panel)
    logger.info(
        "Deduplicated to %d company-years (from %d filings)", len(deduped), len(panel)
    )

    out = Path(args.out) if args.out else root / "fundamental_panel.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    deduped.to_csv(out, index=False)
    logger.info("Panel written: %s", out)

    summary = coverage_summary(deduped)
    (root / "fundamental_panel_coverage.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    print()
    print(json.dumps(summary, indent=2, default=str))

    # Balance-sheet availability drives which factor blocks can be validated, so
    # it is printed per fiscal year rather than as one average that hides the
    # FY2023 discontinuity.
    if "Fiscal_Year" in deduped and "Has_Balance_Sheet" in deduped:
        by_year = (
            deduped.groupby("Fiscal_Year")
            .agg(
                company_years=("Security_ID", "size"),
                balance_sheet_pct=("Has_Balance_Sheet", lambda s: round(100 * s.mean(), 1)),
                cash_flow_pct=("Has_Cash_Flow", lambda s: round(100 * s.mean(), 1)),
                revenue_pct=("Revenue", lambda s: round(100 * s.notna().mean(), 1)),
                eps_pct=("EPS_Basic", lambda s: round(100 * s.notna().mean(), 1)),
            )
        )
        print()
        print("Coverage by fiscal year:")
        print(by_year.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
