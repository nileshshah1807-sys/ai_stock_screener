"""Index constituent lists, for the Market page's movers by index.

One function per source, behind a registry keyed by the prefix of
``LiveIndex.members_source`` (``"nse:ind_nifty50list"``). Display only: no
score reads index membership.

NSE publishes each index's constituents as a CSV on its archive host, the same
host the universe master comes from (``screener.universe``). The file changes
when the index is reconstituted, twice a year plus the odd replacement, so the
quote worker re-reads it once a day rather than every five minutes.

US lists come from Wikipedia, the same tables the US universe is built from
(``screener.universe``). They name no company in a fixed column, so the
company is left empty: a rated member shows the screener's name, an unrated
one its ticker alone.
"""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Callable

import requests

from screener import universe

logger = logging.getLogger(__name__)

NSE_INDEX_CSV_URL = "https://nsearchives.nseindia.com/content/indices/{name}.csv"

_TIMEOUT_SECONDS = 30
# The archive host refuses requests that name no browser.
_USER_AGENT = "Mozilla/5.0 (compatible; winnow-screener/1.0)"


def parse_nse_index_csv(text: str) -> list[tuple[str, str | None]]:
    """``(symbol, company)`` pairs from one NSE constituent file, in file order.

    Headers are matched after stripping, as in the EQUITY_L master, and a row
    with no symbol is skipped rather than failing the list.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if reader.fieldnames is None:
        return []
    reader.fieldnames = [name.strip() for name in reader.fieldnames]
    members: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for row in reader:
        symbol = (row.get("Symbol") or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        company = (row.get("Company Name") or "").strip() or None
        members.append((symbol, company))
    return members


def nse_index(name: str) -> list[tuple[str, str | None]]:
    response = requests.get(
        NSE_INDEX_CSV_URL.format(name=name),
        timeout=_TIMEOUT_SECONDS,
        headers={"User-Agent": _USER_AGENT},
    )
    response.raise_for_status()
    return parse_nse_index_csv(response.text)


def wikipedia_index(key: str) -> list[tuple[str, str | None]]:
    return [(symbol, None) for symbol in universe.wikipedia_index_members(key)]


SOURCES: dict[str, Callable[[str], list[tuple[str, str | None]]]] = {
    "nse": nse_index,
    "wiki": wikipedia_index,
}


def fetch(members_source: str) -> list[tuple[str, str | None]]:
    """Constituents named by a ``"<source>:<name>"`` key."""
    prefix, _, name = members_source.partition(":")
    try:
        source = SOURCES[prefix]
    except KeyError:
        raise ValueError(f"Unknown index members source {members_source!r}") from None
    return source(name)
