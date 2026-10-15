"""Latest-quarter growth from the exchange's own results filings.

The model reads two quarterly inputs, ``Revenue_Growth`` and
``Earnings_Growth``: the most recent quarter against the same quarter a year
earlier. They arrive in the vendor's quote metadata, which trails the exchange.
A company files its results with NSE within minutes of the board meeting; the
vendor republishes them days or weeks later, and the quote cache can hold the
old figure for a further week. Through every results season the growth block
therefore ranks companies that have reported on the quarter before.

NSE's integrated-filing index lists every results filing with the quarter it
covers, its basis and a link to the figures as filed. This module reads the
index and the documents, and measures the same two growth rates from them. The arithmetic is `backtest.fundamentals.QuarterPanel`, the rule the
quarter inputs were validated under, so a live run and the backtest agree by
construction on what "latest-quarter growth" means:

* both quarters filed, and on the same basis (consolidated preferred);
* earnings growth measured on profit, not on EPS;
* a non-positive base quarter has no growth rate.

The documents are fetched and parsed once, by `workers.quarterly_filings`,
which runs through the evening as companies file and stores every filing in
the ``quarterly_filings`` table. That table is also what the stock page's
quarterly results are drawn from, so the screener and the page read the same
figures. A run reads the table; it fetches nothing from the exchange.

Every miss leaves the vendor's figure exactly as it was served:

* a store that cannot be read (or a run with no Supabase credentials, such as
  a validation dispatch) is reported once and growth keeps the vendor's
  figures throughout;
* a company with no comparable pair of filings keeps the vendor's two figures;
* a taxonomy this module does not read (see `SUPPORTED_TAXONOMIES`) keeps the
  vendor's figures;
* a company whose vendor figures already describe a later quarter than its
  filings do keeps them. The index is the exchange's, not a guarantee: a
  filing can be missing from it, or dated to the wrong year by the filer.

When a pair is used, both figures come from it, including one the pair cannot
support (a loss in the base quarter). Filling that one from the vendor would
set two different quarters side by side in the same growth block.
"""

from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from backtest.xbrl import QUARTER_CONTEXT, extract_fact

logger = logging.getLogger(__name__)

SOURCE_LABEL = "NSE integrated filings"

INDEX_URL = "https://www.nseindia.com/api/integrated-filing-results"
INDEX_FILING_TYPE = "Integrated Filing- Financials"
INDEX_PAGE_SIZE = 10000
# nseindia.com and its archive both reject a request without a browser-shaped
# User-Agent and a Referer from the site.
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/118.0"
    ),
    "Accept": "application/json,application/xml,text/xml,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-integrated-filing",
}

STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"
STATUS_DISABLED = "disabled"

# The filing's taxonomy is named in its document link. The commercial
# (Ind-AS and the older Indian GAAP) and NBFC taxonomies share the tags below.
# Banks and insurers file a different statement altogether -- no revenue from
# operations, income split between interest and other, or between the
# policyholders' and shareholders' accounts -- and are left to the vendor.
TAXONOMY_PATTERN = re.compile(r"INTEGRATED_FILING_([A-Z]+)_", re.IGNORECASE)
SUPPORTED_TAXONOMIES = frozenset({"INDAS", "NBFC", "NONINDAS"})

# First tag present in the quarter's own context wins. The tag names differ
# between the Ind-AS and Indian GAAP taxonomies; the lines are the same.
FACT_TAGS = {
    "Revenue": ("RevenueFromOperations",),
    "PAT": (
        "ProfitLossForPeriodFromContinuingOperations",
        "ProfitLossForPeriod",
        "ProfitLossForThePeriodFromContinuingOperations",
        "ProfitLossForThePeriod",
    ),
}

# The quarter's income statement, line by line, for the stock page. The keys
# are the page's row names (`workers.financial_statements`); the choices follow
# what the vendor's statement means by each, so a filed quarter can sit beside
# the vendor's quarters in one table: profit is the owners' share where the
# company reports one (`OWNERS_PROFIT_TAG`), and EPS is diluted before basic.
STATEMENT_TAGS = {
    "revenue": ("RevenueFromOperations",),
    "other_income": ("OtherIncome",),
    "interest": ("FinanceCosts",),
    "depreciation": (
        "DepreciationDepletionAndAmortisationExpense",
        "DepreciationAndAmortisationExpense",
    ),
    "pbt": ("ProfitBeforeTax",),
    "tax": ("TaxExpense",),
    "net_profit": (
        "ProfitLossForPeriod",
        "ProfitLossForPeriodFromContinuingOperations",
        "ProfitLossForThePeriod",
        "ProfitLossForThePeriodFromContinuingOperations",
    ),
    "eps": (
        "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
        "DilutedEarningsLossPerShareFromContinuingOperations",
        "DilutedEarningsLossPerShare",
        "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
        "BasicEarningsLossPerShareFromContinuingOperations",
        "BasicEarningsLossPerShare",
    ),
}

# Profit after the minority's share, which is what the vendor calls net
# income. Many filers leave the line at zero, consolidated or not; a zero
# beside a non-zero profit for the period is an empty field, not a result.
OWNERS_PROFIT_TAG = ("ProfitOrLossAttributableToOwnersOfParent",)

INDEX_COLUMNS = (
    "Symbol",
    "Period_End",
    "Is_Consolidated",
    "Seq_Id",
    "Filed_At",
    "Taxonomy",
    "XBRL_URL",
)
# A stored filing as the growth arithmetic reads it (`facts_frame`).
FACT_COLUMNS = (
    "Symbol",
    "Period_End",
    "Is_Consolidated",
    "Seq_Id",
    "Filed_On",
    "Taxonomy",
    "Revenue",
    "PAT",
)
GROWTH_COLUMNS = (
    "Symbol",
    "Revenue_Growth",
    "Earnings_Growth",
    "Quarter_Period_End",
    "Quarter_Basis",
)

# Bumped whenever `parse_filing` would read a document differently. The
# filings worker then reads every stored filing again, so a fix reaches the
# whole history rather than only what is filed after it.
PARSER_VERSION = 1

# Growth needs the latest quarter and the one a year before it; the store is
# read that far back beyond the age a quarter may have to count as current.
FILING_HISTORY_DAYS = 400

# The quarter the vendor's two growth figures describe, carried on the
# fundamental record so a filing older than it is not preferred. Plumbing
# only: `QuarterlyResultsCollector.enrich` removes it from the frame.
VENDOR_QUARTER_COLUMN = "Vendor_Quarter_End"

def _parse_stamp(value):
    """NSE's timestamp shapes (``08-Oct-2026 22:07:33``, ``30-SEP-2026``)."""
    text = str(value or "").strip()
    if not text or text.lower() in {"-", "nan", "none", "null"}:
        return None
    for pattern in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def vendor_quarter_end(epoch):
    """The vendor's ``mostRecentQuarter`` (epoch seconds) as an ISO date."""
    try:
        return datetime.fromtimestamp(float(epoch), UTC).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def taxonomy_of(url):
    match = TAXONOMY_PATTERN.search(str(url or ""))
    return match.group(1).upper() if match else ""


def normalise_index(records):
    """One row per (symbol, quarter, basis): the latest filing of each.

    A revision is filed under a new id and replaces the original, as it does
    for anyone reading the exchange today. Rows that cannot be placed -- no
    symbol, no quarter end, no document, no filing time -- are dropped.
    """
    rows = []
    for record in records or ():
        symbol = str(record.get("symbol") or "").strip().upper()
        period_end = _parse_stamp(record.get("qe_Date"))
        url = str(record.get("xbrl") or "").strip()
        # A revision carries no broadcast time, only when it was revised.
        filed = (
            _parse_stamp(record.get("broadcast_Date"))
            or _parse_stamp(record.get("revised_Date"))
            or _parse_stamp(record.get("creation_Date"))
        )
        seq_id = str(record.get("seq_Id") or "").strip()
        if not symbol or period_end is None or filed is None or not seq_id:
            continue
        if not url.lower().startswith("http"):
            continue
        basis = str(record.get("consolidated") or "").strip().lower()
        rows.append(
            {
                "Symbol": symbol,
                "Period_End": period_end.date(),
                "Is_Consolidated": basis == "consolidated",
                "Seq_Id": seq_id,
                "Filed_At": filed,
                "Taxonomy": taxonomy_of(url),
                "XBRL_URL": url,
            }
        )
    if not rows:
        return pd.DataFrame(columns=list(INDEX_COLUMNS))
    frame = pd.DataFrame(rows, columns=list(INDEX_COLUMNS))
    frame["_seq"] = pd.to_numeric(frame["Seq_Id"], errors="coerce").fillna(-1)
    frame = frame.sort_values(
        ["Symbol", "Period_End", "Is_Consolidated", "Filed_At", "_seq"]
    )
    frame = frame.drop_duplicates(
        subset=["Symbol", "Period_End", "Is_Consolidated"], keep="last"
    )
    return frame.drop(columns="_seq").reset_index(drop=True)


def first_filings(records):
    """When each company first filed each quarter: ``{(symbol, period): time}``.

    The earliest broadcast across bases. A revision is served with no
    broadcast time and is left out: it restates a quarter, it does not
    announce one.
    """
    first = {}
    for record in records or ():
        symbol = str(record.get("symbol") or "").strip().upper()
        period_end = _parse_stamp(record.get("qe_Date"))
        broadcast = _parse_stamp(record.get("broadcast_Date"))
        if not symbol or period_end is None or broadcast is None:
            continue
        key = (symbol, period_end.date())
        if key not in first or broadcast < first[key]:
            first[key] = broadcast
    return first


def fetch_index(start, end, *, session=None, timeout=60):
    """Every results filing broadcast between two dates, normalised."""
    return normalise_index(
        fetch_index_records(start, end, session=session, timeout=timeout)
    )


def fetch_index_records(start, end, *, session=None, timeout=60):
    """Every results filing broadcast between two dates, as the exchange serves it."""
    if session is None:
        import requests

        session = requests
    collected = []
    page = 1
    while True:
        response = session.get(
            INDEX_URL,
            params={
                "index": "equities",
                "period_ended": "all",
                "type": INDEX_FILING_TYPE,
                "from_date": start.strftime("%d-%m-%Y"),
                "to_date": end.strftime("%d-%m-%Y"),
                "page": str(page),
                "size": str(INDEX_PAGE_SIZE),
            },
            headers=REQUEST_HEADERS,
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        batch = payload.get("data") or []
        collected.extend(batch)
        total = int(payload.get("totalCount") or 0)
        if not batch or len(collected) >= total:
            break
        page += 1
    if not collected:
        # A year and a half of results is tens of thousands of filings; none
        # at all is a failed fetch, not a quiet period.
        raise ValueError("integrated-filing index returned no filings")
    return collected


def parse_quarter_facts(text):
    """The quarter's own revenue and profit from one results document."""
    return {
        field: extract_fact(text, tags, QUARTER_CONTEXT)
        for field, tags in FACT_TAGS.items()
    }


def parse_quarter_statement(text):
    """The quarter's income statement lines from one results document.

    Operating profit is what the vendor calls EBITDA: profit before tax with
    interest and depreciation added back, and only when all three were filed.
    """
    lines = {
        key: extract_fact(text, tags, QUARTER_CONTEXT)
        for key, tags in STATEMENT_TAGS.items()
    }
    owners = extract_fact(text, OWNERS_PROFIT_TAG, QUARTER_CONTEXT)
    if owners:
        lines["net_profit"] = owners
    parts = (lines["pbt"], lines["interest"], lines["depreciation"])
    lines["operating_profit"] = None if None in parts else sum(parts)
    return lines



def parse_filing(text):
    """Everything stored from one results document.

    The income statement lines the stock page draws, plus ``pat``: profit as
    the growth arithmetic measures it (continuing operations first, see
    `FACT_TAGS`), which is not always the line the page calls net profit.
    """
    return {**parse_quarter_statement(text), "pat": parse_quarter_facts(text)["PAT"]}


def facts_frame(rows, timezone):
    """Stored filings (``workers.quarterly_filings``) as `quarter_growth` reads them.

    ``Filed_On`` is the exchange's local date of the filing: a result filed
    this evening is visible to this evening's run.
    """
    records = []
    for row in rows or ():
        filed = pd.Timestamp(row.get("filed_at"))
        if pd.isna(filed):
            continue
        if filed.tzinfo is not None:
            filed = filed.tz_convert(timezone)
        records.append(
            {
                "Symbol": str(row.get("symbol") or "").strip().upper(),
                "Period_End": pd.Timestamp(row.get("period_end")).date(),
                "Is_Consolidated": bool(row.get("is_consolidated")),
                "Seq_Id": str(row.get("seq_id") or ""),
                "Filed_On": filed.date(),
                "Taxonomy": str(row.get("taxonomy") or ""),
                "Revenue": row.get("revenue"),
                "PAT": row.get("pat"),
            }
        )
    return pd.DataFrame(records, columns=list(FACT_COLUMNS))

class DocumentFetcher:
    """Thread-pooled download of results documents from the exchange archive."""

    def __init__(self, *, workers=6, timeout=60, retries=3, session_factory=None):
        self.workers = max(1, int(workers))
        self.timeout = int(timeout)
        self.retries = max(1, int(retries))
        self._session_factory = session_factory
        self._local = threading.local()

    def _session(self):
        # One session per worker thread: requests.Session is not documented
        # as thread-safe.
        session = getattr(self._local, "session", None)
        if session is None:
            if self._session_factory is not None:
                session = self._session_factory()
            else:
                import requests

                session = requests.Session()
                session.headers.update(REQUEST_HEADERS)
            self._local.session = session
        return session

    def fetch_one(self, url):
        """The document's text, or None after the retries are spent."""
        for _attempt in range(self.retries):
            try:
                response = self._session().get(
                    url, timeout=(min(10, self.timeout), self.timeout)
                )
            except Exception as exc:
                logger.debug("Results document fetch failed %s: %s", url, exc)
                continue
            status = getattr(response, "status_code", 200)
            body = response.text or ""
            if status == 200 and body and not body.lstrip()[:15].lower().startswith(
                ("<!doctype html", "<html")
            ):
                return body
            # A missing archive file stays missing; only a throttle is retried.
            if 400 <= status < 500 and status != 429:
                break
        return None

    def fetch_many(self, urls):
        if not urls:
            return []
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            return list(pool.map(self.fetch_one, urls))


def quarter_growth(facts, symbols, *, today, max_age_days):
    """Latest-quarter growth per symbol from cached filing facts.

    ``facts`` is the cache frame. A filing that carried neither figure is not
    evidence about its quarter and is left out, exactly as the backtest's
    panel builder leaves it out.
    """
    empty = pd.DataFrame(columns=list(GROWTH_COLUMNS))
    if facts is None or len(facts) == 0:
        return empty
    # Imported here: the panel pulls in the backtest's fundamentals module,
    # which a market without a filings provider never needs.
    from backtest.fundamentals import QuarterPanel

    working = facts.copy()
    for column in ("Revenue", "PAT"):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    working = working[working["Revenue"].notna() | working["PAT"].notna()]
    if working.empty:
        return empty
    panel = QuarterPanel(
        pd.DataFrame(
            {
                "Security_ID": working["Symbol"].astype(str),
                "Period_End": working["Period_End"],
                # A date, not a time: a filing made today is visible today.
                "Available_From": working["Filed_On"],
                "Is_Consolidated": working["Is_Consolidated"],
                "Revenue": working["Revenue"],
                "PAT": working["PAT"],
            }
        )
    )
    section = panel.cross_section(
        [str(symbol) for symbol in symbols], today, max_age_days=max_age_days
    )
    if section.empty or "Revenue_Growth" not in section:
        return empty
    return section.rename(columns={"Security_ID": "Symbol"})[list(GROWTH_COLUMNS)]


class QuarterlyResultsCollector:
    """Overlay filing-derived quarter growth onto a merged research frame.

    Reads the filings `workers.quarterly_filings` has already fetched and
    parsed into the ``quarterly_filings`` table; nothing here asks the
    exchange for anything. That worker runs through the evening as companies
    file, so a run reads every result filed before it started.
    """

    def __init__(self, config, *, provider=None, filings_loader=None, clock=None):
        self.config = config
        from .markets import active_profile

        self.profile = active_profile(config)
        if provider is None:
            provider = self.profile.quarterly_results_provider
        self.provider = provider
        self.enabled = bool(provider) and bool(
            getattr(config, "QUARTERLY_RESULTS_FILINGS_ENABLED", False)
        )
        # Injectable so tests never touch the store.
        self._filings_loader = filings_loader
        self._clock = clock or (lambda: datetime.now())
        self.diagnostics = {"quarter_results_source_status": STATUS_DISABLED}

    def _max_age_days(self):
        return int(getattr(self.config, "QUARTERLY_RESULTS_MAX_AGE_DAYS", 200))

    def _today(self):
        return pd.Timestamp(self._clock()).date()

    def _load_filings(self, since):
        if self._filings_loader is not None:
            return self._filings_loader(since)
        url = getattr(self.config, "SUPABASE_URL", "")
        key = getattr(self.config, "SUPABASE_SERVICE_ROLE_KEY", "")
        if not url or not key:
            raise RuntimeError("the filing store is not configured (SUPABASE_URL)")
        from storage.supabase_repository import SupabaseRepository

        repository = SupabaseRepository(
            url,
            key,
            int(getattr(self.config, "SUPABASE_TIMEOUT_SECONDS", 30)),
            read_only=bool(getattr(self.config, "SUPABASE_READ_ONLY", False)),
            market=self.profile.code,
        )
        return repository.quarterly_filing_facts(since)

    def _facts(self, today):
        """The stored filings, or None when the store cannot be read."""
        since = today - timedelta(days=self._max_age_days() + FILING_HISTORY_DAYS)
        try:
            rows = self._load_filings(since)
        except Exception as exc:  # an overlay must never be why a run dies
            logger.warning(
                "Stored results filings (%s) unavailable; growth keeps the "
                "vendor's figures this run: %s",
                self.provider,
                exc,
            )
            self.diagnostics["quarter_results_source_status"] = STATUS_UNAVAILABLE
            return None
        facts = facts_frame(rows, self.profile.timezone)
        latest = facts["Filed_On"].max() if len(facts) else None
        self.diagnostics.update(
            {
                "quarter_results_source_status": STATUS_OK,
                "quarter_results_filings_read": int(len(facts)),
                "quarter_results_latest_filed_on": (
                    latest.isoformat() if latest is not None else None
                ),
            }
        )
        return facts

    def collect(self, symbols):
        """Filing-derived growth for ``symbols`` (a priority-ordered list)."""
        wanted = list(
            dict.fromkeys(str(s).strip().upper() for s in symbols if str(s).strip())
        )
        if not self.enabled or not wanted:
            return pd.DataFrame(columns=list(GROWTH_COLUMNS))
        today = self._today()
        return quarter_growth(
            self._facts(today), wanted, today=today, max_age_days=self._max_age_days()
        )

    def enrich(self, frame):
        """Replace the vendor's quarter growth where filings supply a pair."""
        if frame is None or frame.empty or "Symbol" not in frame:
            return frame
        if not self.enabled:
            return self._without_vendor_quarter(frame)
        from .statements import FinancialStatementCollector

        growth = self.collect(FinancialStatementCollector._priority_order(frame))
        keys = frame["Symbol"].astype(str).str.strip().str.upper()
        by_symbol = growth.set_index("Symbol")
        filed_quarter = keys.map(by_symbol["Quarter_Period_End"])
        vendor_quarter = pd.to_datetime(
            frame.get(VENDOR_QUARTER_COLUMN, pd.Series(pd.NaT, index=frame.index)),
            errors="coerce",
        )
        # ISO dates on both sides. An unknown vendor quarter (a row cached
        # before it was recorded, a vendor that omits it) defers to the filing.
        behind = vendor_quarter.notna() & (pd.to_datetime(filed_quarter) < vendor_quarter)
        served = filed_quarter.notna() & ~behind

        counts = filed_quarter[served].value_counts().sort_index()
        self.diagnostics["quarter_results_filing_symbols"] = sorted(keys[served])
        self.diagnostics["quarter_results_vendor_newer_symbols"] = sorted(
            keys[filed_quarter.notna() & behind]
        )
        self.diagnostics["quarter_results_latest_quarter_counts"] = {
            str(period): int(count) for period, count in counts.items()
        }
        logger.info(
            "Quarter growth from %s for %d/%d symbol(s); the rest keep the "
            "vendor's figures. Latest quarter: %s",
            SOURCE_LABEL,
            int(served.sum()),
            len(frame),
            self.diagnostics["quarter_results_latest_quarter_counts"] or "none",
        )
        if not served.any():
            return self._without_vendor_quarter(frame)
        enriched = frame.copy()
        for column in ("Revenue_Growth", "Earnings_Growth"):
            vendor = pd.to_numeric(
                enriched.get(column, pd.Series(np.nan, index=enriched.index)),
                errors="coerce",
            )
            filed = keys.map(by_symbol[column]).astype(float)
            enriched[column] = filed.where(served, vendor)
        return self._without_vendor_quarter(enriched)

    @staticmethod
    def _without_vendor_quarter(frame):
        if VENDOR_QUARTER_COLUMN in frame:
            return frame.drop(columns=VENDOR_QUARTER_COLUMN)
        return frame
