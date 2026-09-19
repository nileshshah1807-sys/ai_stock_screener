"""Compare published stages against a third-party stage screener's export.

`screener/stage.py` was calibrated against one vendor's labels for one
cross-section. That calibration is only worth anything if it is re-checkable, so
this reports the same three numbers the pre-registration recorded -- stage
agreement, days-in-stage error, and RS rank correlation -- for any later export.

Usage::

    python -m tools.compare_stage_labels \\
        --export stage2-stocks_2026-09-19.xlsx stage3-stocks_2026-09-19.xlsx \\
        --screener advanced_analysis_20260919.csv

Exports may be .xlsx (needs openpyxl) or .csv, and are matched on the ticker
with any exchange prefix stripped. The screener CSV is a normal run export; both
sides must describe the same session, and the tool says so if the dates it can
see disagree.

Vendor columns are recognised case-insensitively: a stage column, optionally
"Days in Stage" and an RS percentile. Nothing here is imported by the screener.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

STAGE_ALIASES = {
    "stage 1": "Stage 1",
    "stage 2": "Stage 2",
    "stage 3": "Stage 3",
    "stage 4": "Stage 4",
    "s2 candidate": "S2 Candidate",
    "s2candidate": "S2 Candidate",
    "stage 2 candidate": "S2 Candidate",
}


def _column(frame, *candidates):
    lowered = {str(name).strip().lower(): name for name in frame.columns}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def load_export(paths):
    """One frame of Symbol / Stage / Days / RS from the vendor exports."""
    frames = []
    for path in paths:
        path = Path(path)
        if path.suffix.lower() in {".xlsx", ".xlsm"}:
            try:
                frame = pd.read_excel(path)
            except ImportError as exc:  # openpyxl is not a runtime dependency
                raise SystemExit(
                    f"Reading {path.name} needs openpyxl (pip install openpyxl), "
                    "or export the same view as CSV."
                ) from exc
        else:
            frame = pd.read_csv(path)

        symbol = _column(frame, "symbol", "ticker", "stock")
        stage = _column(frame, "stage")
        if symbol is None or stage is None:
            raise SystemExit(f"{path.name}: need a symbol column and a stage column")
        days = _column(frame, "days in stage", "days (s2)", "days")
        rs = _column(frame, "rs percentile", "rs", "rs rating")

        out = pd.DataFrame(
            {
                # "NSE:DEEDEV" and "DEEDEV.NS" both mean DEEDEV.
                "Symbol": frame[symbol]
                .astype(str)
                .str.split(":")
                .str[-1]
                .str.replace(r"\.(NS|BO)$", "", regex=True)
                .str.strip()
                .str.upper(),
                "Their_Stage": frame[stage]
                .astype(str)
                .str.strip()
                .str.lower()
                .map(lambda value: STAGE_ALIASES.get(value, value.title())),
                "Their_Days": pd.to_numeric(frame[days], errors="coerce")
                if days
                else pd.NA,
                "Their_RS": pd.to_numeric(frame[rs], errors="coerce") if rs else pd.NA,
            }
        )
        frames.append(out)
    merged = pd.concat(frames, ignore_index=True).drop_duplicates("Symbol")
    return merged


def load_screener(path):
    frame = pd.read_csv(path, low_memory=False)
    if "Stage" not in frame.columns:
        raise SystemExit(
            f"{Path(path).name} has no Stage column. It predates screener/stage.py, "
            "or the run had STAGE_TIMING_ENABLED off."
        )
    columns = ["Symbol", "Stage", "Days_In_Stage", "RS_Rating", "Advance_Age_Days"]
    present = [column for column in columns if column in frame.columns]
    out = frame.loc[:, present].copy()
    out["Symbol"] = out["Symbol"].astype(str).str.strip().str.upper()
    return out, frame


def report(export, ours, as_of=None):
    matched = ours.merge(export, on="Symbol", how="inner")
    # A row with no stage is not a disagreement: it is a security with too
    # little price history to classify, and scoring it as a miss would make the
    # agreement figure depend on how many recent listings the vendor covers.
    joined = matched[matched["Stage"].notna()]
    unscored = len(matched) - len(joined)
    print(f"Matched {len(matched)} of {len(export)} exported names"
          f"{f' (screener run {as_of})' if as_of else ''};"
          f" {unscored} have no stage here (too little history) and are excluded.\n")
    if joined.empty:
        return 1

    agree = joined["Stage"] == joined["Their_Stage"]
    print(f"Stage agreement: {agree.mean():.1%}\n")
    matrix = pd.crosstab(joined["Their_Stage"], joined["Stage"], margins=True)
    print("Theirs (rows) against ours (columns):")
    print(matrix.to_string(), "\n")

    if joined["Their_Days"].notna().any() and "Days_In_Stage" in joined:
        same = joined[agree].dropna(subset=["Their_Days", "Days_In_Stage"])
        if len(same):
            error = (same["Days_In_Stage"] - same["Their_Days"]).abs()
            print(
                "Days in stage, where the label agrees: "
                f"median error {error.median():.0f}d, "
                f"within 1d {error.le(1).mean():.0%}, within 7d {error.le(7).mean():.0%}"
            )
            by_stage = same.assign(error=error).groupby("Stage")["error"].median()
            print("  median error by stage:", by_stage.round(0).to_dict(), "\n")

    if joined["Their_RS"].notna().any() and "RS_Rating" in joined:
        pair = joined.dropna(subset=["Their_RS", "RS_Rating"])
        if len(pair) > 2:
            # Pearson on ranks is Spearman, and needs no scipy -- which is not a
            # dependency of this project and must not become one for a report.
            spearman = pair["Their_RS"].rank().corr(pair["RS_Rating"].rank())
            gap = (pair["Their_RS"] - pair["RS_Rating"]).abs().mean()
            print(f"RS rating: Spearman {spearman:.3f}, mean absolute gap {gap:.1f} points")

    # Stages are a vendor's opinion, not a measurement, so a disagreement is
    # reported for inspection rather than treated as an error to fix.
    if (~agree).any():
        print("\nDisagreements (first 20):")
        print(
            joined.loc[~agree, ["Symbol", "Their_Stage", "Stage", "Their_Days"]]
            .head(20)
            .to_string(index=False)
        )
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", nargs="+", required=True,
                        help="vendor export(s): .xlsx or .csv, one per stage")
    parser.add_argument("--screener", required=True,
                        help="a screener run CSV carrying the Stage column")
    args = parser.parse_args(argv)

    export = load_export(args.export)
    ours, raw = load_screener(args.screener)
    as_of = None
    for column in ("Price_Bar_As_Of", "Analysis_As_Of"):
        if column in raw.columns and raw[column].notna().any():
            as_of = str(raw[column].dropna().iloc[0])[:10]
            break
    return report(export, ours, as_of)


if __name__ == "__main__":
    sys.exit(main())
