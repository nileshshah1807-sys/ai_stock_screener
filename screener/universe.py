"""Universe sources: which symbols a market's run considers.

One function per source, behind a registry keyed by ``MarketProfile.universe_source``.
Each returns a :class:`UniverseResult` carrying both the symbols and the
provenance fields the collection diagnostics and the run manifest record, so a
run can always answer "where did this universe come from and did it change".

The NSE source is the fetch that used to live inline in
``StockDataCollector.get_comprehensive_stock_list``, moved here unchanged --
same URL, same status strings, same ``sha256`` over the raw response bytes --
because the manifest hash depends on all three.

Every source here is keyless and returns plain CSV or plain text. That is a
deliberate constraint: ``pandas.read_html`` needs ``lxml``, which is only a
transitive dependency of yfinance and is not reliably installed, so no source
may depend on an HTML parser.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import re
from dataclasses import dataclass, field, replace

import pandas as pd
import requests

from screener.markets import BSE_SUFFIX

logger = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0"
_TIMEOUT_SECONDS = 15

# Wikipedia's robot policy rejects a generic browser User-Agent with HTTP 403
# and asks automated clients to identify themselves and give a contact route.
# Overridable so a fork can point the contact at its own repository.
_WIKI_USER_AGENT = os.getenv(
    "WIKIPEDIA_USER_AGENT",
    "winnow-screener/1.0 (daily equity research screener; +https://github.com/)",
)

NSE_EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
BSE_BHAVCOPY_URL = (
    "https://www.bseindia.com/download/BhavCopy/Equity/"
    "BhavCopy_BSE_CM_0_0_0_{day:%Y%m%d}_F_0000.CSV"
)
# A thinly traded company misses a session now and then; read a week of files
# so a quiet day does not drop it from the universe. Two weeks finds them
# across a holiday run.
_BSE_SESSIONS = 5
_BSE_LOOKBACK_DAYS = 14
# BSE's groups for mainboard equity. SME (M, MT), debt (F, G), ETFs (E) and
# trusts (IF) are left out, as EQUITY_L leaves out their NSE counterparts.
_BSE_MAINBOARD_GROUPS = frozenset({"A", "B", "T", "X", "XT", "Z"})

# Wikipedia's constituent tables are the only free, keyless, complete source for
# the S&P 400 and 600. The MediaWiki API is used rather than the rendered page
# so the response is wikitext -- parseable with a regular expression and no HTML
# parser. Each constituent row names its ticker through an exchange template,
# e.g. ``{{NyseSymbol|AA}}``, which is what the pattern below matches. The
# Nasdaq-100 list writes its tickers as plain text in the first cell instead.
_WIKI_API = (
    "https://en.wikipedia.org/w/api.php"
    "?action=parse&page={page}&prop=wikitext&format=json&formatversion=2"
)
_WIKI_INDEX_PAGES = {
    "sp500": "List_of_S%26P_500_companies",
    "sp400": "List_of_S%26P_400_companies",
    "sp600": "List_of_S%26P_600_companies",
    "ndx100": "List_of_NASDAQ-100_companies",
}
_WIKI_SYMBOL_PATTERN = re.compile(
    r"\{\{\s*(?:Nyse|Nasdaq|NYSE American|Cboe)Symbol\s*\|\s*"
    r"([A-Za-z0-9.\-]{1,8})\s*(?:\|[^}]*)?\}\}"
)
# A row whose first cell is a bare ticker: ``| ADBE || [[Adobe Inc.]] || ...``.
_WIKI_PLAIN_SYMBOL_PATTERN = re.compile(r"^\|\s*([A-Z][A-Z0-9.\-]{0,7})\s*\|\|", re.MULTILINE)

# Official Nasdaq Trader symbol directory: pipe-delimited, no key, and the
# authoritative answer to "what is listed in the US today".
_NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
_OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"


@dataclass(frozen=True)
class UniverseResult:
    """Symbols for one market plus the provenance the manifest records."""

    symbols: tuple[str, ...]
    source_url: str
    status: str
    source_sha256: str | None = None
    source_symbol_count: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)


def _get(
    url: str,
    timeout: int = _TIMEOUT_SECONDS,
    user_agent: str = _USER_AGENT,
) -> requests.Response:
    return requests.get(url, timeout=timeout, headers={"User-Agent": user_agent})


def _to_vendor_symbol(symbol: str) -> str:
    """Normalise a US share-class ticker to the convention yfinance uses.

    Exchanges and Wikipedia write a share class with a dot (``BRK.B``); Yahoo
    writes it with a hyphen (``BRK-B``). Only four S&P 1500 members are
    affected today, but they include Berkshire, and an unnormalised ticker
    fetches nothing at all rather than failing loudly.
    """
    return symbol.strip().upper().replace(".", "-")


def _digest_symbols(symbols) -> str:
    """Hash the derived symbol list rather than the raw response.

    For NSE the raw CSV is stable and is hashed directly. The US sources are
    not: a Wikipedia page is edited many times a day for prose and references,
    so hashing its bytes would report a universe change on almost every run.
    Hashing the sorted symbols answers the question the manifest is actually
    asking -- did the universe change -- rather than did the page change.
    """
    joined = "\n".join(sorted(symbols)).encode("utf-8")
    return hashlib.sha256(joined).hexdigest()


# ---------------------------------------------------------------------------
# NSE
# ---------------------------------------------------------------------------

def _nse_master():
    """Return ``(frame, result)``; ``frame`` is None when the fetch failed."""
    url = NSE_EQUITY_L_URL
    try:
        resp = _get(url)
    except Exception as exc:
        logger.error("NSE Master fetch failed (%s) - falling back to built-in watchlist only!", exc)
        return None, UniverseResult((), url, f"error:{type(exc).__name__}")

    if resp.status_code != 200:
        logger.error(
            "NSE master list returned HTTP %s - falling back to built-in watchlist only!",
            resp.status_code,
        )
        return None, UniverseResult((), url, f"http_{resp.status_code}")

    frame = pd.read_csv(io.StringIO(resp.text))
    frame.columns = [str(column).strip() for column in frame.columns]
    symbols = tuple(frame["SYMBOL"].dropna().str.strip().tolist())
    logger.info("NSE Master: %d symbols", len(symbols))
    return frame, UniverseResult(
        symbols=symbols,
        source_url=url,
        status="ok",
        source_sha256=hashlib.sha256(resp.content).hexdigest(),
        source_symbol_count=len(set(symbols)),
    )


def nse_equity_l(config=None) -> UniverseResult:
    """The NSE equity master list. Behaviour is unchanged from v5.1."""
    return _nse_master()[1]


def _recent_bse_bhavcopies(today=None):
    """The last ``_BSE_SESSIONS`` BSE equity bhavcopies as one frame, or None.

    BSE's scrip-master API refuses a script (its CDN answers 403); the daily
    bhavcopy is a plain file that names every traded security with its ISIN.
    """
    today = today or pd.Timestamp.now(tz="Asia/Kolkata").date()
    frames = []
    for back in range(_BSE_LOOKBACK_DAYS):
        day = today - pd.Timedelta(days=back)
        # No weekend file to find, and BSE stalls the request until it times out.
        if len(frames) == _BSE_SESSIONS or day.weekday() >= 5:
            continue
        url = BSE_BHAVCOPY_URL.format(day=day)
        try:
            resp = _get(url)
        except Exception as exc:
            logger.warning("BSE bhavcopy fetch failed (%s): %s", url, exc)
            continue
        # A day with no session is served as an HTML error page, not a 404.
        if resp.status_code == 200 and resp.content.startswith(b"TradDt"):
            frames.append(pd.read_csv(io.BytesIO(resp.content)))
    return pd.concat(frames, ignore_index=True) if frames else None


def nse_with_bse_only(config=None) -> UniverseResult:
    """NSE's list plus every mainboard equity listed on BSE alone.

    A company on both exchanges is screened once, as NSE's (matched by ISIN).
    The rest carry their Yahoo ticker, ``SYMBOL.BO``, as their symbol, which no
    NSE symbol can equal, so the read-model key stays one company per row.
    """
    nse, result = _nse_master()
    if nse is None:
        return result
    bse = _recent_bse_bhavcopies()
    if bse is None:
        logger.error("No BSE bhavcopy in the last %d days; NSE symbols only", _BSE_LOOKBACK_DAYS)
        return replace(result, status="ok:partial", notes=("bse:unavailable",))

    nse_isins = set(nse["ISIN NUMBER"].dropna().str.strip())
    bse_only = bse[
        bse["FinInstrmTp"].eq("STK")
        & bse["SctySrs"].isin(_BSE_MAINBOARD_GROUPS)
        # A company's ISIN; group B also holds fund units (INF...).
        & bse["ISIN"].str.startswith("INE", na=False)
        & ~bse["ISIN"].isin(nse_isins)
    ]
    added = sorted({f"{symbol.strip().upper()}{BSE_SUFFIX}" for symbol in bse_only["TckrSymb"].dropna()})
    symbols = tuple(dict.fromkeys((*result.symbols, *added)))
    logger.info("NSE + BSE-only universe: %d symbols (%d BSE-only)", len(symbols), len(added))
    return replace(
        result,
        symbols=symbols,
        # Both files change daily for reasons other than the listing, so the
        # manifest records the derived list (as for the US sources).
        source_sha256=_digest_symbols(symbols),
        source_symbol_count=len(symbols),
        notes=(f"nse:{len(result.symbols)}", f"bse_only:{len(added)}"),
    )


# ---------------------------------------------------------------------------
# US
# ---------------------------------------------------------------------------

def wikipedia_index_members(index_key: str) -> tuple[str, ...]:
    """Return one index's constituents from its Wikipedia table."""
    page = _WIKI_INDEX_PAGES[index_key]
    resp = _get(_WIKI_API.format(page=page), timeout=30, user_agent=_WIKI_USER_AGENT)
    resp.raise_for_status()
    wikitext = resp.json()["parse"]["wikitext"]

    # Several of these pages carry a "selected changes" table below the
    # constituents table, listing symbols that have *left* the index. Bounding
    # the search to the constituents table keeps those out.
    start = wikitext.find('id="constituents"')
    if start >= 0:
        end = wikitext.find("\n|}", start)
        wikitext = wikitext[start:end] if end > start else wikitext[start:]

    symbols = _WIKI_SYMBOL_PATTERN.findall(wikitext) or _WIKI_PLAIN_SYMBOL_PATTERN.findall(wikitext)
    members = {_to_vendor_symbol(match) for match in symbols}
    if not members:
        raise ValueError(f"No constituents parsed from Wikipedia page {page!r}")
    return tuple(sorted(members))


def _sp_composite(index_keys: tuple[str, ...], label: str) -> UniverseResult:
    symbols: set[str] = set()
    notes: list[str] = []
    for key in index_keys:
        try:
            members = wikipedia_index_members(key)
        except Exception as exc:
            # A partial composite is still a usable research universe, and is
            # far better than failing the whole run. The shortfall is recorded
            # so the manifest shows the universe was incomplete that day.
            logger.error("%s constituent fetch failed: %s", key.upper(), exc)
            notes.append(f"{key}:error:{type(exc).__name__}")
            continue
        notes.append(f"{key}:{len(members)}")
        symbols.update(members)

    if not symbols:
        return UniverseResult((), _WIKI_API, "error:no_constituents", notes=tuple(notes))

    status = "ok" if all(":error:" not in note for note in notes) else "ok:partial"
    logger.info("%s universe: %d symbols (%s)", label, len(symbols), ", ".join(notes))
    return UniverseResult(
        symbols=tuple(sorted(symbols)),
        source_url=_WIKI_API,
        status=status,
        source_sha256=_digest_symbols(symbols),
        source_symbol_count=len(symbols),
        notes=tuple(notes),
    )


def sp500(config=None) -> UniverseResult:
    """S&P 500 constituents (~500 large-cap names)."""
    return _sp_composite(("sp500",), "S&P 500")


def sp1500(config=None) -> UniverseResult:
    """S&P Composite 1500: the 500, 400 and 600 unioned (~1,500 names)."""
    return _sp_composite(("sp500", "sp400", "sp600"), "S&P 1500")


# Security names whose instruments are not common stock. Warrants, units,
# rights, preferred lines and notes all trade under their own tickers in the
# Nasdaq directory and have no meaningful fundamentals to score.
_NON_COMMON_MARKERS = (
    " warrant",
    " unit",
    " right",
    " preferred",
    " depositary share",
    " subordinated note",
    " due 20",
    "%",
)

# Common shares that are not operating companies. Closed-end funds and SPACs
# list as ordinary common stock with no ETF flag, so only the security name
# identifies them: on the 2026-09-23 directory this matched 297 funds and 228
# SPACs, and no S&P 1500 member. A fund's "fundamentals" are its portfolio and a
# SPAC's are a trust account, so neither belongs in a cross-sectional ranking of
# businesses. Word-bounded on purpose: "Income Trust" is also how several REITs
# are named, so trusts are left to the liquidity and statement-coverage gates.
_NON_OPERATING_PATTERN = re.compile(
    r"\bfunds?\b"
    r"|\bmunicipal|\bmuniyield"
    r"|\bacquisition (?:corp|corporation|co|company|limited|ltd|inc)\b"
    r"|\bmerger corp",
    re.IGNORECASE,
)


def _parse_nasdaq_directory(text: str, symbol_column: str) -> pd.DataFrame:
    frame = pd.read_csv(io.StringIO(text), sep="|", dtype=str)
    # Both files end with a "File Creation Time" trailer row that has no symbol.
    frame = frame[frame[symbol_column].notna()]
    return frame[~frame[symbol_column].str.contains("File Creation Time", na=False)]


def all_listed(config=None) -> UniverseResult:
    """Every US-listed operating company, from the Nasdaq Trader symbol directory.

    ETFs, test issues, non-common lines, closed-end funds and SPACs are
    dropped here. Liquidity is not: the runtime's research prefilter applies
    the price and turnover floors once prices are in, before the slow
    fundamentals and statements fetches.
    """
    symbols: set[str] = set()
    notes: list[str] = []

    for url, symbol_column in (
        (_NASDAQ_LISTED_URL, "Symbol"),
        (_OTHER_LISTED_URL, "ACT Symbol"),
    ):
        try:
            resp = _get(url, timeout=30)
            resp.raise_for_status()
            frame = _parse_nasdaq_directory(resp.text, symbol_column)
        except Exception as exc:
            logger.error("Nasdaq directory fetch failed for %s: %s", url, exc)
            notes.append(f"{url.rsplit('/', 1)[-1]}:error:{type(exc).__name__}")
            continue

        keep = frame[symbol_column].notna()
        if "ETF" in frame.columns:
            keep &= frame["ETF"].fillna("N").str.upper().ne("Y")
        if "Test Issue" in frame.columns:
            keep &= frame["Test Issue"].fillna("N").str.upper().ne("Y")
        if "Security Name" in frame.columns:
            lowered = frame["Security Name"].fillna("").str.lower()
            for marker in _NON_COMMON_MARKERS:
                keep &= ~lowered.str.contains(marker, regex=False)
            keep &= ~lowered.str.contains(_NON_OPERATING_PATTERN, regex=True)

        selected = frame.loc[keep, symbol_column].str.strip().str.upper().str.replace(
            ".", "-", regex=False
        )
        # "$" marks preferred and similar non-common lines in the CQS symbology.
        selected = selected[~selected.str.contains(r"[$]", regex=True, na=False)]
        notes.append(f"{url.rsplit('/', 1)[-1]}:{len(selected)}")
        symbols.update(selected.tolist())

    if not symbols:
        return UniverseResult((), _NASDAQ_LISTED_URL, "error:no_symbols", notes=tuple(notes))

    status = "ok" if all(":error:" not in note for note in notes) else "ok:partial"
    logger.info("US listed universe: %d common stocks (%s)", len(symbols), ", ".join(notes))
    return UniverseResult(
        symbols=tuple(sorted(symbols)),
        source_url=_NASDAQ_LISTED_URL,
        status=status,
        source_sha256=_digest_symbols(symbols),
        source_symbol_count=len(symbols),
        notes=tuple(notes),
    )


SOURCES = {
    "nse_equity_l": nse_equity_l,
    "nse_with_bse_only": nse_with_bse_only,
    "sp500": sp500,
    "sp1500": sp1500,
    "all_listed": all_listed,
}

# The URL a source reads, known before the fetch so the collection diagnostics
# can name its provenance from construction rather than only after a
# successful request -- which is what a failed run needs to report.
SOURCE_URLS = {
    "nse_equity_l": NSE_EQUITY_L_URL,
    "nse_with_bse_only": NSE_EQUITY_L_URL,
    "sp500": _WIKI_API,
    "sp1500": _WIKI_API,
    "all_listed": _NASDAQ_LISTED_URL,
}


def resolve_source(profile, config=None) -> str:
    """Return the universe source key for a run.

    ``{MARKET}_UNIVERSE_SOURCE`` (``US_UNIVERSE_SOURCE``, ``NSE_UNIVERSE_SOURCE``)
    lets a market's universe be widened or narrowed without a code change, which
    is why the size decision is a setting rather than a literal. Each market
    reads only its own.
    """
    setting = f"{profile.code}_UNIVERSE_SOURCE"
    override = str(getattr(config, setting, "") or "").strip().lower()
    if override:
        if override not in SOURCES:
            known = ", ".join(sorted(SOURCES))
            raise ValueError(f"Unknown {setting} {override!r}; expected one of: {known}")
        return override
    return profile.universe_source


def fetch(profile, config=None) -> UniverseResult:
    """Fetch the universe for ``profile``, honouring any configured override."""
    source = resolve_source(profile, config)
    return SOURCES[source](config)
