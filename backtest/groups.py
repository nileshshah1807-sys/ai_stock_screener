"""A point-in-time coarse NSE group map, rebuilt from archived Nifty 500 lists.

The bhavcopy carries no sector, and today's map would leak survivorship
(`backtest/gates.py`). NSE's own constituent file -- Company, Industry, Symbol,
ISIN -- was archived by the Wayback Machine 16 times between Oct 2018 and Oct
2026, and `tools.build_group_map` turns those captures into ``group_map.csv``.

Each capture is dated by its Wayback timestamp: the list was public by then.
A security takes its label from the latest capture on or before the signal
date that lists it; one first listed later takes that later label and is
flagged back-filled, so a result can be checked without them. A security never
in the Nifty 500 has no group.

NSE replaced its taxonomy in 2022 (``AUTOMOBILE`` became ``Automobile and Auto
Components``, ``CONSTRUCTION`` split into ``Construction`` and ``Realty``, and
so on), so only a coarse level is consistent across the period.
`COARSE_GROUPS` folds both vocabularies into it; the folds follow how the 402
companies listed in both the Jul 2020 and May 2022 captures were relabelled.
Fixed on 30 Oct 2026, before any result (WNN-23).
"""

from __future__ import annotations

import pandas as pd

COARSE_GROUPS = {
    "Auto": ("AUTOMOBILE", "Automobile and Auto Components"),
    "Capital Goods": ("INDUSTRIAL MANUFACTURING", "Capital Goods"),
    "Chemicals": ("CHEMICALS", "FERTILISERS & PESTICIDES", "Chemicals"),
    # The old label covered builders and developers alike.
    "Construction & Realty": ("CONSTRUCTION", "Construction", "Realty"),
    "Construction Materials": ("CEMENT & CEMENT PRODUCTS", "Construction Materials"),
    "Consumer Goods": (
        "CONSUMER GOODS", "Consumer Durables", "Fast Moving Consumer Goods", "Diversified",
    ),
    "Services": ("SERVICES", "Services", "Consumer Services"),
    # Until 2020 oil, gas and power were one label, ENERGY.
    "Energy": ("ENERGY", "OIL & GAS", "POWER", "Oil Gas & Consumable Fuels", "Power"),
    "Financial Services": ("FINANCIAL SERVICES", "Financial Services"),
    "Healthcare": ("PHARMA", "HEALTHCARE SERVICES", "Healthcare"),
    "IT": ("IT", "Information Technology"),
    "Media": ("MEDIA & ENTERTAINMENT", "Media Entertainment & Publication"),
    "Metals": ("METALS", "Metals & Mining"),
    "Paper": ("PAPER", "Forest Materials"),
    "Telecom": ("TELECOM", "Telecommunication"),
    "Textiles": ("TEXTILES", "Textiles"),
}

INDUSTRY_TO_GROUP = {
    industry: group for group, industries in COARSE_GROUPS.items() for industry in industries
}


def coarse_group(industry):
    """The coarse group for an NSE industry label; KeyError on an unknown label."""
    return INDUSTRY_TO_GROUP[str(industry).strip()]


class GroupMap:
    """Security_ID -> coarse group as of a date, from ``group_map.csv`` rows."""

    def __init__(self, rows):
        table = rows[["Security_ID", "Snapshot_Date", "Group"]].copy()
        table["Security_ID"] = table["Security_ID"].astype(str)
        table["Snapshot_Date"] = pd.to_datetime(table["Snapshot_Date"])
        self._table = table.sort_values("Snapshot_Date").reset_index(drop=True)

    @classmethod
    def from_csv(cls, path):
        return cls(pd.read_csv(path))

    def as_of(self, security_ids, signal_date):
        """``(group, backfilled)`` Series aligned to ``security_ids``."""
        ids = pd.Series(security_ids).astype(str)
        probe = pd.DataFrame({
            "Security_ID": ids.to_numpy(),
            "Snapshot_Date": pd.Timestamp(signal_date),
            "_order": range(len(ids)),
        })
        backward, forward = (
            pd.merge_asof(probe, self._table, on="Snapshot_Date", by="Security_ID",
                          direction=direction).sort_values("_order")
            for direction in ("backward", "forward")
        )
        group = backward["Group"].fillna(forward["Group"])
        backfilled = backward["Group"].isna() & forward["Group"].notna()
        index = getattr(security_ids, "index", None)
        return (
            pd.Series(group.to_numpy(), index=index, dtype=object),
            pd.Series(backfilled.to_numpy(), index=index, dtype=bool),
        )


def group_relative_strength(returns_6m, groups, *, min_members=8):
    """Median 6-month return of each stock's group minus the cross-section median.

    The benchmark is the universe median, as `Model5` uses for market relative
    strength. A group with fewer than ``min_members`` returns (production's
    ``FACTOR_MIN_SECTOR_PEERS``) and an unmapped stock get NaN: no evidence,
    not a weak reading.
    """
    returns = pd.to_numeric(returns_6m, errors="coerce")
    mapped = groups.notna()
    by_group = returns.where(mapped).groupby(groups.where(mapped))
    median = by_group.transform("median")
    count = by_group.transform("count")
    return (median - returns.median()).where(mapped & (count >= min_members))
