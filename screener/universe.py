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
from dataclasses import dataclass, field

import pandas as pd
import requests

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

# Wikipedia's constituent tables are the only free, keyless, complete source for
# the S&P 400 and 600. The MediaWiki API is used rather than the rendered page
# so the response is wikitext -- parseable with a regular expression and no HTML
# parser. Each constituent row names its ticker through an exchange template,
# e.g. ``{{NyseSymbol|AA}}``, which is what the pattern below matches.
_WIKI_API = (
    "https://en.wikipedia.org/w/api.php"
    "?action=parse&page={page}&prop=wikitext&format=json&formatversion=2"
)
_SP_INDEX_PAGES = {
    "sp500": "List_of_S%26P_500_companies",
    "sp400": "List_of_S%26P_400_companies",
    "sp600": "List_of_S%26P_600_companies",
}
_WIKI_SYMBOL_PATTERN = re.compile(
    r"\{\{\s*(?:Nyse|Nasdaq|NYSE American|Cboe)Symbol\s*\|\s*"
    r"([A-Za-z0-9.\-]{1,8})\s*(?:\|[^}]*)?\}\}"
)

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

def nse_equity_l(config=None) -> UniverseResult:
    """The NSE equity master list. Behaviour is unchanged from v5.1."""
    url = NSE_EQUITY_L_URL
    try:
        resp = _get(url)
    except Exception as exc:
        logger.error("NSE Master fetch failed (%s) - falling back to built-in watchlist only!", exc)
        return UniverseResult((), url, f"error:{type(exc).__name__}")

    if resp.status_code != 200:
        logger.error(
            "NSE master list returned HTTP %s - falling back to built-in watchlist only!",
            resp.status_code,
        )
        return UniverseResult((), url, f"http_{resp.status_code}")

    frame = pd.read_csv(io.StringIO(resp.text))
    symbols = tuple(frame["SYMBOL"].dropna().str.strip().tolist())
    logger.info("NSE Master: %d symbols", len(symbols))
    return UniverseResult(
        symbols=symbols,
        source_url=url,
        status="ok",
        source_sha256=hashlib.sha256(resp.content).hexdigest(),
        source_symbol_count=len(set(symbols)),
    )


# ---------------------------------------------------------------------------
# US
# ---------------------------------------------------------------------------

def _wikipedia_index_members(index_key: str) -> tuple[str, ...]:
    """Return one S&P index's constituents from its Wikipedia table."""
    page = _SP_INDEX_PAGES[index_key]
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

    members = {_to_vendor_symbol(match) for match in _WIKI_SYMBOL_PATTERN.findall(wikitext)}
    if not members:
        raise ValueError(f"No constituents parsed from Wikipedia page {page!r}")
    return tuple(sorted(members))


def _sp_composite(index_keys: tuple[str, ...], label: str) -> UniverseResult:
    symbols: set[str] = set()
    notes: list[str] = []
    for key in index_keys:
        try:
            members = _wikipedia_index_members(key)
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
    "sp500": sp500,
    "sp1500": sp1500,
    "all_listed": all_listed,
}

# The URL a source reads, known before the fetch so the collection diagnostics
# can name its provenance from construction rather than only after a
# successful request -- which is what a failed run needs to report.
SOURCE_URLS = {
    "nse_equity_l": NSE_EQUITY_L_URL,
    "sp500": _WIKI_API,
    "sp1500": _WIKI_API,
    "all_listed": _NASDAQ_LISTED_URL,
}


def resolve_source(profile, config=None) -> str:
    """Return the universe source key for a run.

    ``US_UNIVERSE_SOURCE`` lets the US universe be widened or narrowed without a
    code change, which is why the size decision is a setting rather than a
    literal. Other markets use their profile's source directly.
    """
    from screener.markets import US

    if profile.code == US:
        override = str(getattr(config, "US_UNIVERSE_SOURCE", "") or "").strip().lower()
        if override:
            if override not in SOURCES:
                known = ", ".join(sorted(SOURCES))
                raise ValueError(
                    f"Unknown US_UNIVERSE_SOURCE {override!r}; expected one of: {known}"
                )
            return override
    return profile.universe_source


def fetch(profile, config=None) -> UniverseResult:
    """Fetch the universe for ``profile``, honouring any configured override."""
    source = resolve_source(profile, config)
    return SOURCES[source](config)
