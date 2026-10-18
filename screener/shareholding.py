"""Who owns an NSE company, and who traded large blocks of it, as the exchange discloses.

Two disclosures, both display evidence for the stock page's Shareholding tab;
nothing scores them.

* **Shareholding pattern** (SEBI LODR Regulation 31), filed within 21 days of
  each quarter end. The exchange's index (``INDEX_URL``) lists every filing
  with a link to its XBRL document; ``parse_pattern`` reads the document into
  the four groups a reader compares -- promoter, FII, DII, public -- plus the
  named holders the format requires (every promoter, and every public holder
  of at least 1%).
* **Bulk and block deals**, published every session. ``fetch_deals`` reads the
  exchange's history export, whose CSV form is complete where its JSON form
  stops at 70 rows.

The groups are the exchange's own subtotals, not a sum of named holders: FII
is "Institutions (Foreign)", DII "Institutions (Domestic)", and public what is
left after those and the promoter -- so employee trusts and the government
count as public, as every Indian results site prints it. Filings made before
SEBI split institutions into domestic and foreign (September 2022) have no
such subtotals and would read as no FII or DII at all; the worker does not
reach back that far.
"""

from __future__ import annotations

import csv
import io
import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime

from screener.numeric import round_half_up, safe_float
from screener.quarterly_results import REQUEST_HEADERS

logger = logging.getLogger(__name__)

INDEX_URL = "https://www.nseindia.com/api/corporate-share-holdings-master"
DEALS_URL = "https://www.nseindia.com/api/historicalOR/bulk-block-short-deals"
DEAL_KINDS = {"bulk": "bulk_deals", "block": "block_deals"}

# Bump to have every stored pattern read again.
PARSER_VERSION = 1

_INSTANCE = "{http://www.xbrl.org/2003/instance}"
_DIMENSION = "{http://xbrl.org/2006/xbrldi}"
_CATEGORY_AXIS = "CategoryOfShareholdersAxis"

# Named-holder tables, by the words in their axis. Since June 2025 every
# promoter row carries a TypeOfPromoterShareholding fact; before it, promoters
# are told by the promoter-only tables below.
# shortcut: foreign promoters' tables are not listed (none in the sample read),
# so before June 2025 a foreign promoter shows as public; add their axes if one turns up.
_PROMOTER_AXES = (
    "DetailsSharesHeldByIndividualsOrHUFAxis",
    "DetailsOfSharesHeldByCentralGovernmentOrStateGovernmentsAxis",
    "DetailsOfSharesHeldByOthersIndianShareholdersAxis",
)
_FOREIGN_INSTITUTION_WORDS = (
    "ForeignPortfolioInvestor", "OtherInstitutionsForeign", "ForeignDirectInvestment",
    "ForeignVentureCapital", "SovereignWealthFundsForeign", "OverseasDepositories",
)
_DOMESTIC_INSTITUTION_WORDS = (
    "MutualFunds", "InsuranceCompanies", "OtherFinancialInstitutions",
    "OtherInstitutionsDomestic", "ProvidentFunds", "PensionFunds", "Banks",
    "AlternativeInvestmentFunds", "VentureCapitalFunds", "NBFCs",
    "AssetReconstruction", "SovereignWealthFundsDomestic", "OtherInstitutionsAxis",
)
# Persons acting in concert repeat holders listed elsewhere.
# Below the 1% a public holder must be named at, a row is a category total
# ("Clearing Members") rather than a holder.
_PUBLIC_NAMED_FROM = 1.0
_SKIPPED_AXES = ("PersonsInConcert", "SignificantBeneficialOwners", "Unclaimed")


def _session(session):
    if session is not None:
        return session
    import requests

    fresh = requests.Session()
    fresh.headers.update(REQUEST_HEADERS)
    return fresh


def fetch_index_records(start: date, end: date, *, session=None, timeout=120) -> list[dict]:
    """Every shareholding pattern broadcast between two dates, as the exchange serves it."""
    response = _session(session).get(
        INDEX_URL,
        params={
            "index": "equities",
            "from_date": start.strftime("%d-%m-%Y"),
            "to_date": end.strftime("%d-%m-%Y"),
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else payload.get("data") or []


def _parse_date(value) -> date | None:
    try:
        return datetime.strptime(str(value).strip(), "%d-%b-%Y").date()
    except ValueError:
        return None


def _parse_stamp(value) -> datetime | None:
    try:
        return datetime.strptime(str(value).strip(), "%d-%b-%Y %H:%M:%S")
    except ValueError:
        return None


def _is_quarter_end(day: date) -> bool:
    # A pattern is also filed for an allotment or a listing, as of that day;
    # the quarterly series a reader compares is the quarter-end ones.
    return (day.month, day.day) in {(3, 31), (6, 30), (9, 30), (12, 31)}


def quarter_filings(records: list[dict]) -> list[dict]:
    """The latest filing of each (symbol, quarter end), newest broadcast first."""
    latest: dict[tuple[str, date], dict] = {}
    for record in records:
        period_end = _parse_date(record.get("date"))
        filed_at = _parse_stamp(record.get("broadcastDate"))
        url = record.get("xbrl")
        symbol = str(record.get("symbol") or "").strip().upper()
        if not (symbol and period_end and filed_at and url) or not _is_quarter_end(period_end):
            continue
        row = {
            "symbol": symbol,
            "period_end": period_end,
            "record_id": str(record.get("recordId")),
            "filed_at": filed_at,
            "document_url": url,
            "company": record.get("name") or None,
        }
        have = latest.get((symbol, period_end))
        if have is None or filed_at > have["filed_at"]:
            latest[(symbol, period_end)] = row
    return sorted(latest.values(), key=lambda row: row["filed_at"], reverse=True)


def _holder_group(axis: str, promoter: bool) -> str:
    if promoter:
        return "promoter"
    if any(word in axis for word in _FOREIGN_INSTITUTION_WORDS):
        return "fii"
    if any(word in axis for word in _DOMESTIC_INSTITUTION_WORDS):
        return "dii"
    return "public"


def parse_pattern(text: str) -> dict:
    """A shareholding-pattern XBRL document as the groups and named holders.

    Percentages are of total shares, in percent. Every group is None when the
    document has no grand total to read it against.
    """
    root = ET.fromstring(text.encode() if isinstance(text, str) else text)
    contexts: dict[str, tuple[str, str]] = {}
    for context in root.iter(f"{_INSTANCE}context"):
        explicit = [
            (member.get("dimension", "").split(":")[-1], (member.text or "").split(":")[-1])
            for member in context.iter(f"{_DIMENSION}explicitMember")
        ]
        typed = [
            (member.get("dimension", "").split(":")[-1], "".join(member.itertext()).strip())
            for member in context.iter(f"{_DIMENSION}typedMember")
        ]
        dims = explicit + typed
        if len(dims) == 1:
            contexts[context.get("id")] = dims[0]

    categories: dict[str, dict[str, str]] = {}
    holders: dict[tuple[str, str], dict[str, str]] = {}
    for fact in root:
        dim = contexts.get(fact.get("contextRef"))
        if dim is None or fact.text is None:
            continue
        tag = fact.tag.split("}")[-1]
        axis, member = dim
        target = categories.setdefault(member, {}) if axis == _CATEGORY_AXIS else (
            holders.setdefault(dim, {})
        )
        target[tag] = fact.text.strip()

    total = categories.get("ShareholdingPatternMember") or {}
    # Filings since mid-2025 state shares as a fraction (total 1); earlier
    # ones as a percentage (total 100).
    whole = safe_float(total.get("ShareholdingAsAPercentageOfTotalNumberOfShares"))
    scale = 1 if whole is not None and whole > 1.5 else 100

    def percent(value):
        number = safe_float(value)
        return None if number is None else round_half_up(number * scale, 2)

    def pct(member):
        return percent((categories.get(member) or {}).get(
            "ShareholdingAsAPercentageOfTotalNumberOfShares"
        ))

    def group(member):
        # A complete filing has no subtotal for a group nobody is in: a company
        # with no promoter, or no foreign institution on its register.
        value = pct(member)
        return 0.0 if value is None and whole is not None else value

    promoter = group("ShareholdingOfPromoterAndPromoterGroupMember")
    fii = group("InstitutionsForeignMember")
    dii = group("InstitutionsDomesticMember")
    public = (
        round_half_up(100 - promoter - fii - dii, 2)
        if None not in (promoter, fii, dii)
        else None
    )
    typed_promoters = any("TypeOfPromoterShareholding" in facts for facts in holders.values())

    named = []
    for (axis, _member), facts in holders.items():
        name = (facts.get("NameOfTheShareholder") or "").strip()
        share = percent(facts.get("ShareholdingAsAPercentageOfTotalNumberOfShares"))
        if not name or share is None or any(word in axis for word in _SKIPPED_AXES):
            continue
        # "Any other" tables name a category's total after the category ("HUF").
        labels = {value.strip().lower() for tag, value in facts.items() if tag.startswith("CategoryOf")}
        if name.lower() in labels:
            continue
        is_promoter = (
            "TypeOfPromoterShareholding" in facts
            if typed_promoters
            else bool(promoter) and axis in _PROMOTER_AXES
        )
        if not is_promoter and share < _PUBLIC_NAMED_FROM:
            continue
        named.append({
            "name": name,
            "group": _holder_group(axis, is_promoter),
            "pct": share,
            "shares": safe_float(facts.get("NumberOfShares")),
        })
    named.sort(key=lambda holder: holder["pct"], reverse=True)

    return {
        "promoter": promoter,
        "fii": fii,
        "dii": dii,
        "public": public,
        "shareholders": safe_float(total.get("NumberOfShareholders")),
        "shares": safe_float(total.get("NumberOfShares")),
        "holders": named,
    }


def _number(value) -> float | None:
    return safe_float(str(value or "").replace(",", "").strip() or None)


def parse_deals(text: str, kind: str) -> list[dict]:
    """The history export's CSV as deal rows, one per printed trade."""
    rows = []
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    for raw in reader:
        record = {(key or "").strip(): (value or "").strip() for key, value in raw.items()}
        deal_date = _parse_date(record.get("Date"))
        symbol = record.get("Symbol", "").upper()
        quantity = _number(record.get("Quantity Traded"))
        price = _number(record.get("Trade Price / Wght. Avg. Price"))
        if not (deal_date and symbol and quantity is not None and price is not None):
            continue
        rows.append({
            "kind": kind,
            "deal_date": deal_date.isoformat(),
            "symbol": symbol,
            "client_name": record.get("Client Name", ""),
            "side": record.get("Buy / Sell", "").upper(),
            "quantity": int(quantity),
            "price": price,
            "remarks": None if record.get("Remarks", "-") in ("", "-") else record["Remarks"],
        })
    return rows


def fetch_deals(kind: str, start: date, end: date, *, session=None, timeout=180) -> list[dict]:
    """Every bulk or block deal between two dates (the exchange serves a year at most)."""
    response = _session(session).get(
        DEALS_URL,
        params={
            "optionType": DEAL_KINDS[kind],
            "from": start.strftime("%d-%m-%Y"),
            "to": end.strftime("%d-%m-%Y"),
            "csv": "true",
        },
        timeout=timeout,
    )
    # An empty window is a header and status 200; anything else failed.
    response.raise_for_status()
    return parse_deals(response.content.decode("utf-8-sig", "replace"), kind)
