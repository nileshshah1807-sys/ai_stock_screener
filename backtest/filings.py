"""Point-in-time filing metadata: when each financial statement became public.

This is the module P0 item 1 is really about. A fundamental backtest is only
honest if, on every historical decision date, it uses the figure an investor
could actually have seen. That requires knowing *when* each statement was
published, which no price feed and no current-snapshot data source carries.

NSE's ``corporates-financial-results`` endpoint does carry it, to the minute:

* ``filingDate`` / ``broadCastDate`` / ``exchdisstime`` -- when the filing reached
  the exchange and was disseminated
* ``fromDate`` / ``toDate`` -- the period the statement covers
* ``isin`` -- a stable identifier, bridged through the security master
* ``consolidated`` / ``audited`` -- which basis was reported
* ``xbrl`` -- a link to the numbers **as originally filed**, which is what makes
  original-versus-restated separable at all
* ``seqNumber`` -- a unique filing id, so a re-filing is a new version rather than
  an overwrite

Two coverage limits, both measured rather than assumed, and both are properties
of the source that no amount of engineering here removes:

* **The archive stops in January 2025.** RELIANCE's last filing is 2025-01-16,
  TCS 2025-01-09, 20MICRONS 2025-01-23, and symbol-scoped queries reaching back to
  2007 confirm this is real coverage rather than a query artifact. Fundamentals
  therefore end there; later dates stay price-only.
* **Ind-AS XBRL begins in 2018.** Zero Ind-AS documents before it; roughly 98%
  from 2020 onward. Earlier filings use the pre-Ind-AS Indian GAAP taxonomy and
  are deliberately out of scope, so this module ingests 2018 onward only.

The availability rule is conservative, per `p0.md`: a filing is usable from the
**next completed trading session** after it was broadcast, whether it landed
before or after the close. Filing at 15:15 does not mean the market had digested
it by 15:30.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

FILINGS_SCHEMA_VERSION = 1

# Ind-AS XBRL coverage begins here; earlier filings use a different taxonomy.
IND_AS_FROM_YEAR = 2018

# Measured ceiling of the NSE financial-results archive. Kept as a constant so a
# run that silently produces nothing after this date has a documented reason.
ARCHIVE_COVERAGE_ENDS = date(2025, 1, 31)

FILING_COLUMNS = (
    "Seq_Number",
    "ISIN",
    "Symbol",
    "Company",
    "Period_Start",
    "Period_End",
    "Relating_To",
    "Financial_Year",
    "Filing_Timestamp",
    "Broadcast_Timestamp",
    "Available_From",
    "Consolidated",
    "Audited",
    "Cumulative",
    "Period_Type",
    "XBRL_URL",
    "Is_Ind_AS",
)


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def parse_nse_timestamp(value):
    """Parse the several timestamp shapes NSE emits, or None."""
    text = str(value or "").strip()
    if not text or text in {"-", "nan", "None"}:
        return None
    for pattern in (
        "%d-%b-%Y %H:%M:%S",
        "%d-%b-%Y %H:%M",
        "%d-%b-%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    try:
        return pd.Timestamp(text).to_pydatetime()
    except Exception:
        return None


def _flag(value, true_token):
    return str(value or "").strip().lower() == true_token.lower()


def normalise_filings(records, *, min_year=IND_AS_FROM_YEAR):
    """Normalise raw ``financial_results`` records to the filing schema.

    Rows without a usable ISIN, period end or broadcast timestamp are dropped:
    each is required to place the filing in time, and a filing that cannot be
    placed in time is worse than no filing at all in a point-in-time store.
    """
    rows = []
    for record in records or []:
        isin = str(record.get("isin") or "").strip().upper()
        period_end = parse_nse_timestamp(record.get("toDate"))
        broadcast = parse_nse_timestamp(
            record.get("broadCastDate") or record.get("filingDate")
        )
        filed = parse_nse_timestamp(
            record.get("filingDate") or record.get("broadCastDate")
        )
        if not isin or period_end is None or broadcast is None:
            continue

        xbrl = str(record.get("xbrl") or "").strip()
        is_ind_as = "INDAS" in xbrl.upper()
        if broadcast.year < int(min_year):
            continue

        period_start = parse_nse_timestamp(record.get("fromDate"))
        rows.append(
            {
                "Seq_Number": str(record.get("seqNumber") or "").strip(),
                "ISIN": isin,
                "Symbol": str(record.get("symbol") or "").strip().upper(),
                "Company": str(record.get("companyName") or "").strip(),
                "Period_Start": period_start.date().isoformat() if period_start else "",
                "Period_End": period_end.date().isoformat(),
                "Relating_To": str(record.get("relatingTo") or "").strip(),
                "Financial_Year": str(record.get("financialYear") or "").strip(),
                "Filing_Timestamp": filed.isoformat() if filed else "",
                "Broadcast_Timestamp": broadcast.isoformat(),
                # Filled in by attach_availability once a calendar is known.
                "Available_From": "",
                "Consolidated": _flag(record.get("consolidated"), "Consolidated"),
                "Audited": _flag(record.get("audited"), "Audited"),
                "Cumulative": _flag(record.get("cumulative"), "Cumulative"),
                "Period_Type": str(record.get("period") or "").strip(),
                "XBRL_URL": xbrl,
                "Is_Ind_AS": is_ind_as,
            }
        )

    frame = pd.DataFrame(rows, columns=list(FILING_COLUMNS))
    if frame.empty:
        return frame
    # One row per exchange filing. NSE occasionally repeats a record across
    # overlapping date windows; seqNumber is the exchange's own unique id.
    return (
        frame.drop_duplicates(subset=["Seq_Number", "ISIN", "Period_End"])
        .sort_values(["ISIN", "Period_End", "Broadcast_Timestamp"])
        .reset_index(drop=True)
    )


def attach_availability(frame, calendar):
    """Set ``Available_From`` to the next completed session after broadcast.

    The conservative rule from `p0.md`: information broadcast during a session was
    not necessarily actionable within it, and information broadcast after the
    close obviously was not. Both therefore become usable on the following
    session. This is the single place look-ahead could enter the fundamental
    path, which is why it is one function rather than a scattered comparison.
    """
    if frame is None or len(frame) == 0:
        return frame
    working = frame.copy()
    available = []
    for value in working["Broadcast_Timestamp"]:
        stamp = parse_nse_timestamp(value)
        if stamp is None:
            available.append("")
            continue
        session = calendar.next_session(stamp.date())
        available.append(session.isoformat() if session else "")
    working["Available_From"] = available
    return working


def assign_versions(frame):
    """Number filings per (security, period) in broadcast order.

    Version 1 is the figure as originally reported. A later filing for the same
    period is a restatement, and both are kept: a June-2023 decision must see the
    original even after a 2024 revision replaces it everywhere else.
    """
    if frame is None or len(frame) == 0:
        return frame
    working = frame.copy()
    key = ["ISIN", "Period_End", "Consolidated"]
    working = working.sort_values(key + ["Broadcast_Timestamp"])
    working["Version"] = working.groupby(key).cumcount() + 1
    working["Is_Restatement"] = working["Version"] > 1
    counts = working.groupby(key)["Version"].transform("max")
    working["Version_Count"] = counts
    return working.reset_index(drop=True)


class FilingStore:
    """Fetch, cache and version annual filing metadata."""

    def __init__(self, path, *, nse_factory=None):
        self.path = Path(path)
        self._nse_factory = nse_factory

    def _make_nse(self, download_folder):
        if self._nse_factory is not None:
            return self._nse_factory(download_folder)
        from nse import NSE

        return NSE(download_folder=download_folder, timeout=90, server=False)

    def load(self):
        if not self.path.exists():
            return pd.DataFrame(columns=list(FILING_COLUMNS))
        try:
            return pd.read_csv(self.path, dtype={"ISIN": str, "Seq_Number": str})
        except Exception as exc:
            logger.warning("Filing cache unreadable: %s", exc)
            return pd.DataFrame(columns=list(FILING_COLUMNS))

    def fetch(self, start_year, end_year, *, period="annual", segment="equities"):
        """Fetch filing metadata year by year.

        Year-sized windows rather than one large range: the endpoint filters on
        filing date, and a year is small enough to keep each response bounded
        while needing only a handful of requests in total. Per-symbol queries
        would need ~2,100 requests to retrieve the same rows.
        """
        from tempfile import TemporaryDirectory

        collected = []
        with TemporaryDirectory(prefix="nse_filings_") as folder:
            with self._make_nse(folder) as nse:
                for year in range(int(start_year), int(end_year) + 1):
                    try:
                        records = nse.financial_results(
                            segment=segment,
                            period=period,
                            from_date=datetime(year, 1, 1),
                            to_date=datetime(year, 12, 31, 23, 59, 59),
                        )
                    except Exception as exc:
                        logger.warning("Filing fetch failed for %s: %s", year, exc)
                        continue
                    logger.info("  %s: %d %s filings", year, len(records), period)
                    collected.extend(records)

        frame = normalise_filings(collected)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(self.path, index=False)
        return frame

    def save(self, frame):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(self.path, index=False)
        return self.path


class PointInTimeFilings:
    """Resolve which filing was knowable on a given date.

    The core query of the whole fundamental path: for security *s* on date *t*,
    the most recent filing whose ``Available_From`` is on or before *t*, taking
    the latest version published by then -- not the latest version that exists
    today.
    """

    def __init__(self, frame, master=None):
        self.master = master
        self._by_key: dict[str, list] = {}
        if frame is None or len(frame) == 0:
            return

        for record in frame.to_dict("records"):
            available = str(record.get("Available_From") or "").strip()
            if not available:
                continue
            key = self._key(record.get("ISIN"))
            if key is None:
                continue
            try:
                available_date = date.fromisoformat(available[:10])
                period_end = date.fromisoformat(str(record["Period_End"])[:10])
            except (ValueError, KeyError, TypeError):
                continue
            self._by_key.setdefault(key, []).append(
                {
                    "available_from": available_date,
                    "period_end": period_end,
                    "consolidated": bool(record.get("Consolidated")),
                    "version": int(record.get("Version") or 1),
                    "seq": str(record.get("Seq_Number") or ""),
                    "xbrl": str(record.get("XBRL_URL") or ""),
                    "is_ind_as": bool(record.get("Is_Ind_AS")),
                }
            )
        for entries in self._by_key.values():
            entries.sort(key=lambda item: (item["period_end"], item["available_from"]))

    def _key(self, isin):
        isin = str(isin or "").strip().upper()
        if not isin:
            return None
        if self.master is not None:
            resolved = self.master.security_id_for_isin(isin)
            if resolved:
                return resolved
        return isin

    def known_periods(self, key, as_of, *, limit=None, prefer_consolidated=True):
        """Filings for ``key`` knowable on ``as_of``, newest period first.

        Where a period has several versions available by ``as_of``, the latest of
        those is used -- which is what an investor reading the filings on that
        date would have had, and specifically **not** a later restatement.
        """
        as_of = _as_date(as_of)
        entries = self._by_key.get(str(key))
        if not entries:
            return []

        best: dict[date, dict] = {}
        for entry in entries:
            if entry["available_from"] > as_of:
                continue
            period = entry["period_end"]
            current = best.get(period)
            if current is None:
                best[period] = entry
                continue
            # Prefer the consolidated basis, then the most recent version known.
            if prefer_consolidated and entry["consolidated"] != current["consolidated"]:
                if entry["consolidated"]:
                    best[period] = entry
                continue
            if entry["available_from"] >= current["available_from"]:
                best[period] = entry

        ordered = [best[period] for period in sorted(best, reverse=True)]
        return ordered[: int(limit)] if limit else ordered

    def latest_known(self, key, as_of, **kwargs):
        periods = self.known_periods(key, as_of, limit=1, **kwargs)
        return periods[0] if periods else None

    def coverage(self, as_of):
        """How many securities had any filing knowable on ``as_of``."""
        as_of = _as_date(as_of)
        return sum(
            1
            for entries in self._by_key.values()
            if any(entry["available_from"] <= as_of for entry in entries)
        )

    def __len__(self):
        return len(self._by_key)
