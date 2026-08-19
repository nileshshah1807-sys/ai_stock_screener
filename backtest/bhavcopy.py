"""NSE daily bhavcopy ingestion — the point-in-time universe and price source.

The bhavcopy for a date *is* the tradable universe on that date. Every symbol
that traded appears in it, including symbols that were later delisted, renamed or
suspended. Reconstructing the universe from today's ``EQUITY_L.csv`` instead
would silently restrict every historical cross-section to companies that
survived until today, which is the single largest source of inflated backtest
performance.

Two file formats exist and both are handled:

* **UDIFF** (trade dates from 2024-07-08): carries ``ISIN``, ``TckrSymb`` and a
  ``FinInstrmTp`` discriminator, because the same file also contains derivatives.
* **Legacy** (before 2024-07-08): ``SYMBOL``/``SERIES`` with an ``ISIN`` column.

Both carry ISIN, so the security master can be ISIN-keyed across the whole
window without bridging identifier schemes.

Normalisation is pure and separated from fetching so the parsing rules can be
tested against fixture frames without touching the network.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Bump when a normalised column's meaning changes, so a stale day-file cannot mix
# an incompatible definition into a historical cross-section.
BHAVCOPY_SCHEMA_VERSION = 1

# The date NSE switched the cash-market bhavcopy to the UDIFF layout.
UDIFF_SWITCH_DATE = date(2024, 7, 8)

# Series that represent ordinary investable equity in the normal market.
#
# ``EQ`` is the rolling-settlement equity series. ``BE`` is the trade-for-trade
# segment: still ordinary equity an investor can buy, but delivery-only, so it is
# included and left for the liquidity rules to judge rather than being dropped
# here on a technicality. Everything else is deliberately excluded -- ``SM``/``ST``
# are the SME board, ``GB``/``GS``/``TB`` are government securities, ``BZ`` is the
# surveillance/suspended segment, and ``N0``-``N9``/``IV`` are debt and warrant
# instruments. None of them belong in an equity cross-section.
DEFAULT_SERIES = frozenset({"EQ", "BE"})

# Stable normalised schema. Order is fixed so a day-file diff stays readable.
NORMALISED_COLUMNS = (
    "Trade_Date",
    "ISIN",
    "Symbol",
    "Series",
    "Open",
    "High",
    "Low",
    "Close",
    "Prev_Close",
    "Last",
    "Volume",
    "Turnover_INR",
    "Trades",
)

_UDIFF_MAP = {
    "TckrSymb": "Symbol",
    "SctySrs": "Series",
    "OpnPric": "Open",
    "HghPric": "High",
    "LwPric": "Low",
    "ClsPric": "Close",
    "PrvsClsgPric": "Prev_Close",
    "LastPric": "Last",
    "TtlTradgVol": "Volume",
    "TtlTrfVal": "Turnover_INR",
    "TtlNbOfTxsExctd": "Trades",
}

_LEGACY_MAP = {
    "SYMBOL": "Symbol",
    "SERIES": "Series",
    "OPEN": "Open",
    "HIGH": "High",
    "LOW": "Low",
    "CLOSE": "Close",
    "PREVCLOSE": "Prev_Close",
    "LAST": "Last",
    "TOTTRDQTY": "Volume",
    "TOTTRDVAL": "Turnover_INR",
    "TOTALTRADES": "Trades",
}

_NUMERIC_COLUMNS = (
    "Open",
    "High",
    "Low",
    "Close",
    "Prev_Close",
    "Last",
    "Volume",
    "Turnover_INR",
    "Trades",
)


def is_udiff_date(trade_date):
    """Whether ``trade_date`` uses the UDIFF layout rather than the legacy one."""
    return _as_date(trade_date) >= UDIFF_SWITCH_DATE


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def detect_format(frame):
    """Return ``"udiff"`` or ``"legacy"`` from the columns actually present.

    Detected from content rather than assumed from the date, so a file served in
    an unexpected layout fails loudly at parse time instead of producing a frame
    of silently empty prices.
    """
    columns = {str(column).strip() for column in frame.columns}
    if "TckrSymb" in columns:
        return "udiff"
    if "SYMBOL" in columns:
        return "legacy"
    raise ValueError(
        "Unrecognised bhavcopy layout: expected TckrSymb (UDIFF) or SYMBOL "
        f"(legacy), got {sorted(columns)[:12]}"
    )


def normalise_bhavcopy(frame, trade_date, series=DEFAULT_SERIES):
    """Normalise a raw bhavcopy frame to the stable schema.

    Pure and side-effect free: the caller supplies the frame, so the parsing
    rules are unit-testable without a network round trip.

    ``trade_date`` is taken from the caller rather than the file. The legacy
    layout stores it as ``TIMESTAMP`` in a locale-ish ``10-JAN-2024`` form and
    the UDIFF layout as ``TradDt``; trusting the requested date keeps one
    authority for which session a row belongs to.
    """
    if frame is None or len(frame) == 0:
        return pd.DataFrame(columns=list(NORMALISED_COLUMNS))

    trade_date = _as_date(trade_date)
    working = frame.copy()
    # The legacy file ships some columns with a leading space (' SERIES').
    working.columns = [str(column).strip() for column in working.columns]
    layout = detect_format(working)
    mapping = _UDIFF_MAP if layout == "udiff" else _LEGACY_MAP

    missing = sorted(set(mapping) - set(working.columns))
    if missing:
        raise ValueError(
            f"{layout} bhavcopy for {trade_date} is missing columns: {missing}"
        )

    # The UDIFF cash-market file also carries derivatives. Restrict to stocks
    # before anything else so an option row can never reach the cross-section.
    if layout == "udiff" and "FinInstrmTp" in working.columns:
        instrument = working["FinInstrmTp"].astype(str).str.strip().str.upper()
        working = working.loc[instrument.eq("STK")]

    out = pd.DataFrame(index=working.index)
    for source, target in mapping.items():
        out[target] = working[source]

    out["ISIN"] = (
        working["ISIN"].astype(str).str.strip().str.upper()
        if "ISIN" in working.columns
        else ""
    )
    out["Symbol"] = out["Symbol"].astype(str).str.strip().str.upper()
    out["Series"] = out["Series"].astype(str).str.strip().str.upper()
    out["Trade_Date"] = trade_date.isoformat()

    for column in _NUMERIC_COLUMNS:
        out[column] = pd.to_numeric(out[column], errors="coerce")

    if series:
        out = out.loc[out["Series"].isin({str(s).strip().upper() for s in series})]

    # A row without a usable close cannot price a fill or a return, and a row
    # without an ISIN cannot be tied to the security master across a rename.
    out = out.loc[out["Close"].notna() & out["Close"].gt(0) & out["ISIN"].ne("")]
    out = out.loc[~out["ISIN"].str.upper().isin({"NAN", "NONE", ""})]

    # One row per security per session. A duplicate would double-count the name
    # in an equal-weight benchmark and distort every percentile around it.
    out = out.drop_duplicates(subset=["ISIN"], keep="first")

    return out.loc[:, list(NORMALISED_COLUMNS)].sort_values("Symbol").reset_index(
        drop=True
    )


class BhavcopyStore:
    """Fetch, cache and serve normalised daily bhavcopy panels.

    One gzipped CSV per session under ``root``. Per-day files keep the ingest
    resumable and each day independently inspectable, which matters because a
    single malformed session would otherwise be invisible inside one large file.

    The NSE client is injected so tests never reach the network.
    """

    def __init__(self, root, *, nse_factory=None, series=DEFAULT_SERIES, clock=None):
        self.root = Path(root)
        self.series = frozenset(str(s).strip().upper() for s in series)
        self._nse_factory = nse_factory
        self._clock = clock or (lambda: datetime.now())

    def day_path(self, trade_date):
        """Cache path for one session. Sharded by year to keep listings small."""
        trade_date = _as_date(trade_date)
        return (
            self.root
            / f"v{BHAVCOPY_SCHEMA_VERSION}"
            / str(trade_date.year)
            / f"{trade_date.isoformat()}.csv.gz"
        )

    def has_day(self, trade_date):
        return self.day_path(trade_date).exists()

    def load_day(self, trade_date):
        """Return the cached panel for one session, or None when not cached."""
        path = self.day_path(trade_date)
        if not path.exists():
            return None
        try:
            frame = pd.read_csv(path, compression="gzip", dtype={"ISIN": str})
        except Exception as exc:
            logger.warning("Bhavcopy day-file unreadable (%s): %s", path.name, exc)
            return None
        if frame.empty or "ISIN" not in frame.columns:
            return None
        return frame

    def _make_nse(self, download_folder):
        if self._nse_factory is not None:
            return self._nse_factory(download_folder)
        from nse import NSE

        return NSE(download_folder=download_folder, timeout=90, server=False)

    def fetch_day(self, trade_date):
        """Download, normalise and cache one session.

        Returns the normalised frame on success. Raises on a genuine fetch or
        parse failure so the caller -- which owns the calendar and knows whether
        a session was even expected -- decides what the failure means.
        """
        from tempfile import TemporaryDirectory

        trade_date = _as_date(trade_date)
        with TemporaryDirectory(prefix="bhavcopy_") as download_folder:
            with self._make_nse(download_folder) as nse:
                raw_path = nse.equityBhavcopy(
                    date=datetime.combine(trade_date, datetime.min.time())
                )
                raw = pd.read_csv(raw_path, dtype={"ISIN": str})
        frame = normalise_bhavcopy(raw, trade_date, series=self.series)
        if frame.empty:
            raise ValueError(f"Bhavcopy for {trade_date} normalised to zero rows")
        self.write_day(trade_date, frame)
        return frame

    def write_day(self, trade_date, frame):
        path = self.day_path(trade_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False, compression="gzip")
        return path

    def get_day(self, trade_date):
        """Cached panel if present, otherwise fetch it."""
        cached = self.load_day(trade_date)
        if cached is not None:
            return cached
        return self.fetch_day(trade_date)

    def cached_dates(self):
        """Every session already cached, ascending."""
        base = self.root / f"v{BHAVCOPY_SCHEMA_VERSION}"
        if not base.exists():
            return []
        dates = []
        for path in base.glob("*/*.csv.gz"):
            try:
                dates.append(date.fromisoformat(path.name[: -len(".csv.gz")]))
            except ValueError:
                logger.debug("Ignoring unparseable day-file name %s", path.name)
        return sorted(dates)


def candidate_sessions(start, end, market_holidays=()):
    """Weekdays in ``[start, end]`` that are not configured exchange holidays.

    A candidate is a date worth *asking* the exchange about. Whether a session
    actually occurred is settled by whether a bhavcopy exists, which is
    authoritative in a way a hand-maintained holiday list is not.
    """
    from screener.market_data import is_expected_nse_session

    start = _as_date(start)
    end = _as_date(end)
    out = []
    current = start
    while current <= end:
        if is_expected_nse_session(current, market_holidays):
            out.append(current)
        current += timedelta(days=1)
    return out
