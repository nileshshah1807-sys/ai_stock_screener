"""US (S&P 500) earnings-call transcripts, a few a day, from Alpha Vantage, found through EDGAR.

A call is found by its results 8-K (Item 2.02) in the company's EDGAR filing index;
the 8-K's accession is the filing's key (``transcript_filings``, exchange ``US``).
Alpha Vantage is asked by fiscal quarter, which is the company's own: the quarter
after the last 10-Q/10-K filed before the 8-K, as that filing's cover page labels
it (``dei:EntityCommonStockSharesOutstanding`` carries its ``fy``/``fp``). A filing
the cover-page facts do not reach (Berkshire tags its share count by class, which
the concept endpoint leaves out), or whose label disagrees with the company's
others, is labelled from its period end and the company's fiscal year end
(``periodic_filings``).

Each run spends at most ``--budget`` requests (default 24: the free key allows 25 a
day and ``workers.us_upcoming`` takes one), newest 8-K first, so this season's calls
come before older ones and whatever budget is left fills in past quarters, one day
at a time -- there is no bulk backfill. A call Alpha Vantage does not have yet is
asked again on later runs, at most ``MAX_ATTEMPTS`` times. A refusal (allowance
spent, bad key) stops the run without marking anything.

The text is stored as an ordinary transcript (``market = 'US'``, extraction method
``api:alphavantage``), so the tone and outlook workers read it as they read NSE's.
``--dry-run`` fetches and prints, and stores nothing: a trial of the key.

Display evidence until the US screener's transcript flag is turned on; a failure
warns and never fails the workflow.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import logging
import os
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from transcripts.alphavantage import KEY_ENV, Refused, fetch_transcript, transcript_text
from transcripts.periods import reporting_period_end_for_call

logger = logging.getLogger(__name__)

EXCHANGE = "US"
EXTRACTION_METHOD = "api:alphavantage"
DAILY_REQUESTS = 24
LOOKBACK_DAYS = 400  # about five quarters of 8-Ks: this season's calls and four to fill in
MAX_ATTEMPTS = 3
MIN_TEXT_CHARACTERS = 1000
# The free key refuses a second request within a second (19 Nov 2026), and the refusal ends the run.
REQUEST_SPACING_SECONDS = 1.5
SHARES_CONCEPT = ("dei", "EntityCommonStockSharesOutstanding")
PERIODIC_FORMS = {"10-Q", "10-K"}
NEXT_QUARTER = {"Q1": 2, "Q2": 3, "Q3": 4, "FY": 1}
QUARTER_NUMBER = {"Q1": 1, "Q2": 2, "Q3": 3, "FY": 4}


@dataclass(frozen=True)
class Release:
    """A results 8-K: one call to look for."""

    symbol: str
    cik: int
    accession: str
    filed: date
    accepted: str | None
    company: str | None
    periodic: tuple[tuple[str, str, date, date], ...]  # the company's 10-Q/10-Ks: accession, form, filed, period end
    fiscal_year_end: str | None  # EDGAR's "MMDD"


@dataclass(frozen=True)
class Periodic:
    """A 10-Q or 10-K as its cover page labels it."""

    accession: str
    filed: date
    fy: int
    fp: str
    period_end: date | None


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def results_releases(symbol: str, cik: int, submissions: dict[str, Any], *, since: date, until: date) -> list[Release]:
    """The company's results 8-Ks filed in ``[since, until]``.

    shortcut: reads ``filings.recent`` only (the latest 1,000 filings or a year),
    so a prolific filer's older 8-Ks are not found; read ``filings.files`` if the
    fill-in of past quarters needs them.
    """
    recent = (submissions.get("filings") or {}).get("recent") or {}
    columns = ("form", "items", "filingDate", "accessionNumber", "reportDate", "acceptanceDateTime")
    rows = list(zip(*(recent.get(name) or [] for name in columns)))
    periodic = tuple(
        (accession, form, filed, period_end)
        for form, _, filed_at, accession, report_date, _ in rows
        if form in PERIODIC_FORMS and (filed := _day(filed_at)) and (period_end := _day(report_date))
    )
    releases = []
    for form, items, filed_at, accession, _, accepted in rows:
        filed = _day(filed_at)
        if form != "8-K" or "2.02" not in str(items or "") or filed is None or not since <= filed <= until:
            continue
        releases.append(Release(
            symbol, cik, accession, filed, accepted or None, submissions.get("name"),
            periodic, submissions.get("fiscalYearEnd") or None,
        ))
    return releases


def _year_end_label(form: str, period_end: date, fiscal_year_end: str | None) -> tuple[int, str] | None:
    """A filing's fiscal year and period from its period end and the company's year end ("MMDD")."""
    try:
        month, day = int(str(fiscal_year_end)[:2]), int(str(fiscal_year_end)[2:4])

        def year_end(year: int) -> date:
            return date(year, month, min(day, calendar.monthrange(year, month)[1]))

        end = year_end(period_end.year)
    except ValueError:
        return None
    if end < period_end - timedelta(days=14):  # 52/53-week years end a few days either side
        end = year_end(period_end.year + 1)
    fp = "FY" if form == "10-K" else {3: "Q3", 6: "Q2", 9: "Q1"}.get(((end - period_end).days + 15) // 30)
    return (end.year, fp) if fp else None


def periodic_filings(concept: dict[str, Any] | None, release: Release) -> list[Periodic]:
    """The company's 10-Qs and 10-Ks with their fiscal year and period, one per filing.

    A company's cover labels sit at one offset from its fiscal year end (Target names
    a year by the year it starts, Walmart by the year it ends). The offset most of
    its filings agree on is the company's; a filing that disagrees with it is
    mislabelled (Target's November 2022 10-Q says fiscal 2023, Salesforce's FY2026
    10-K says 2025) and takes the label the offset gives, as does a filing the
    cover-page facts do not reach. A filing with no period end is left as labelled.
    """
    report_dates = {accession: period_end for accession, _, _, period_end in release.periodic}
    cover: dict[str, tuple[str, date, int, str]] = {}
    for facts in ((concept or {}).get("units") or {}).values():
        for fact in facts:
            accession, filed, fp = fact.get("accn"), _day(fact.get("filed")), fact.get("fp")
            if fact.get("form") not in PERIODIC_FORMS or fp not in QUARTER_NUMBER or filed is None or accession in cover:
                continue
            try:
                cover[accession] = (fact["form"], filed, int(fact.get("fy")), fp)
            except (TypeError, ValueError):
                continue
    forms = {accession: (form, filed) for accession, form, filed, _ in release.periodic}
    forms.update({accession: (form, filed) for accession, (form, filed, _, _) in cover.items()})
    by_year_end = {
        accession: label
        for accession, (form, _) in forms.items()
        if accession in report_dates and (label := _year_end_label(form, report_dates[accession], release.fiscal_year_end))
    }
    offsets = Counter(
        fy - by_year_end[accession][0]
        for accession, (_, _, fy, fp) in cover.items()
        if accession in by_year_end and by_year_end[accession][1] == fp
    )
    offset = offsets.most_common(1)[0][0] if offsets else 0
    found = []
    for accession, (_, filed) in forms.items():
        if accession in by_year_end:
            fy, fp = by_year_end[accession][0] + offset, by_year_end[accession][1]
        else:
            _, _, fy, fp = cover[accession]
        found.append(Periodic(accession, filed, fy, fp, report_dates.get(accession)))
    return sorted(found, key=lambda p: p.filed)


def _next_period_end(period_end: date) -> date:
    """Three months on: month end to month end, or 13 weeks for a 52/53-week year."""
    if period_end.day != calendar.monthrange(period_end.year, period_end.month)[1]:
        return period_end + timedelta(weeks=13)
    month = period_end.month + 3
    year = period_end.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return date(year, month, calendar.monthrange(year, month)[1])


def fiscal_quarter(periodic: list[Periodic], release_day: date) -> tuple[str, date] | None:
    """Alpha Vantage's quarter label (``2026Q3``) and the period end of the call a results 8-K announces."""
    before = [p for p in periodic if p.filed < release_day]
    if not before:
        return None
    last = before[-1]
    fy, quarter = last.fy + (last.fp == "FY"), NEXT_QUARTER[last.fp]
    end = _next_period_end(last.period_end) if last.period_end else None
    if end is not None and end >= release_day:
        # The 10-Q went in before the release: the release is about that quarter.
        fy, quarter, end = last.fy, QUARTER_NUMBER[last.fp], last.period_end
    return f"{fy}Q{quarter}", end or reporting_period_end_for_call(release_day)


def _pending(stored: dict[str, Any] | None) -> bool:
    if stored is None:
        return True
    return stored.get("status") not in {"document_ready", "rejected"} and int(stored.get("attempt_count") or 0) < MAX_ATTEMPTS


def run(
    repo,
    edgar,
    symbols: Iterable[str],
    *,
    key: str,
    today: date,
    budget: int = DAILY_REQUESTS,
    lookback_days: int = LOOKBACK_DAYS,
    fetch: Callable[[str, str, str], dict[str, Any]] = fetch_transcript,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, int]:
    counts = dict.fromkeys(
        ("releases", "pending", "requests", "stored", "not_yet", "failed", "same_quarter", "no_quarter", "sec_errors", "refused"),
        0,
    )
    stored = {row["seq_id"]: row for row in repo.transcript_filings(EXCHANGE)}
    releases: list[Release] = []
    for symbol in symbols:
        try:
            cik = edgar.cik_for(symbol)
            if cik is not None:
                releases += results_releases(
                    symbol, cik, edgar.submissions(cik) or {},
                    since=today - timedelta(days=lookback_days), until=today - timedelta(days=1),
                )
        except Exception as exc:  # noqa: BLE001 -- one company's index must not stop the others
            counts["sec_errors"] += 1
            logger.warning("EDGAR index unreadable for %s: %s", symbol, exc)
    counts["releases"] = len(releases)
    pending = sorted((r for r in releases if _pending(stored.get(r.accession))), key=lambda r: r.filed, reverse=True)
    counts["pending"] = len(pending)

    periodic_by_cik: dict[int, list[Periodic]] = {}
    asked: set[tuple[str, str]] = set()
    for release in pending:
        if counts["requests"] >= budget:
            break
        try:
            if release.cik not in periodic_by_cik:
                periodic_by_cik[release.cik] = periodic_filings(edgar.concept(release.cik, *SHARES_CONCEPT), release)
        except Exception as exc:  # noqa: BLE001
            counts["sec_errors"] += 1
            logger.warning("EDGAR cover pages unreadable for %s: %s", release.symbol, exc)
            continue
        found = fiscal_quarter(periodic_by_cik[release.cik], release.filed)
        if found is None:
            counts["no_quarter"] += 1
            continue
        label, period_end = found
        if (release.symbol, label) in asked:
            # A second results 8-K for a quarter this run already asked about (FedEx files two some days).
            counts["same_quarter"] += 1
            continue
        asked.add((release.symbol, label))
        if repo.has_transcript(release.symbol, period_end.isoformat()):
            # A second 8-K for a quarter already stored (a pre-announcement, a correction).
            counts["same_quarter"] += 1
            if not dry_run:
                filing = repo.upsert_filing(_filing(release, label))
                repo.update_filing(filing["id"], status="rejected", last_error=f"a transcript of {label} is stored")
            continue
        counts["requests"] += 1
        filing = None if dry_run else repo.upsert_filing(_filing(release, label))
        try:
            if counts["requests"] > 1:
                sleep(REQUEST_SPACING_SECONDS)
            text = transcript_text(fetch(release.symbol, label, key))
        except Refused as exc:
            counts["requests"] -= 1
            counts["refused"] = 1
            logger.warning("Alpha Vantage refused (%s); the rest wait for the next run", exc)
            break
        except Exception as exc:  # noqa: BLE001
            error = str(exc).replace(key, "***")  # an HTTP error's message carries the URL, which holds the key
            counts["failed"] += 1
            _failed(repo, filing, error)
            logger.warning("Transcript of %s %s not fetched: %s", release.symbol, label, error)
            continue
        if len(text) < MIN_TEXT_CHARACTERS:
            counts["not_yet"] += 1
            _failed(repo, filing, f"Alpha Vantage has no transcript of {label} yet")
            logger.info("No transcript of %s %s yet (8-K %s)", release.symbol, label, release.filed)
            continue
        counts["stored"] += 1
        logger.info(
            "%s %s %s (8-K %s): %d characters, %d turns",
            "Stored" if filing else "Fetched (dry run)", release.symbol, label, release.filed,
            len(text), text.count("\n\n") + 1,
        )
        if filing:
            _store(repo, filing, release, period_end, text)
    logger.info("US transcripts: %s%s", counts, " (dry run, nothing written)" if dry_run else "")
    return counts


def _filing(release: Release, label: str) -> dict[str, Any]:
    return {
        "exchange": EXCHANGE,
        "seq_id": release.accession,
        "symbol": release.symbol,
        "company_name": release.company,
        "announcement_date": release.accepted or release.filed.isoformat(),
        "attachment_url": f"https://www.sec.gov/Archives/edgar/data/{release.cik}/{release.accession.replace('-', '')}/",
        "description": f"Results 8-K (Item 2.02); call {label} from Alpha Vantage",
    }


def _failed(repo, filing: dict[str, Any] | None, error: str) -> None:
    if filing:
        repo.update_filing(
            filing["id"], status="failed", attempt_count=int(filing.get("attempt_count") or 0) + 1, last_error=error[:1000]
        )


def _store(repo, filing: dict[str, Any], release: Release, period_end: date, text: str) -> None:
    raw = text.encode("utf-8")
    sha256 = hashlib.sha256(raw).hexdigest()
    document = repo.find_document_by_sha256(sha256) or repo.create_document(
        {"sha256": sha256, "size_bytes": len(raw), "extraction_method": EXTRACTION_METHOD}
    )
    repo.upsert_transcript({
        "document_id": document["id"],
        "symbol": release.symbol,
        "quarter": period_end.isoformat(),
        # The release's filing day: most calls are held that day or the next morning.
        "call_date": release.filed.isoformat(),
        "cleaned_text": text,
        "token_count": (len(text) + 3) // 4,
        "text_hash": sha256,
    })
    repo.link_filing_document(filing["id"], document["id"])
    repo.update_filing(filing["id"], status="document_ready", last_error=None)


def sp500_members(repo) -> list[str]:
    """The S&P 500 as the live-quotes worker stored it today (``index_members``); Wikipedia if that fails."""
    try:
        members = repo.index_members("S&P 500")
        if len(members) >= 400:
            return members
        logger.warning("index_members holds %d S&P 500 names; reading Wikipedia instead", len(members))
    except Exception as exc:  # noqa: BLE001
        logger.warning("index_members unreadable (%s); reading Wikipedia instead", exc)
    from screener.universe import sp500

    return list(sp500().symbols)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--budget", type=int, default=int(os.getenv("US_TRANSCRIPT_DAILY_REQUESTS", DAILY_REQUESTS)))
    parser.add_argument("--lookback-days", type=int, default=LOOKBACK_DAYS)
    parser.add_argument("--symbols", nargs="*", help="only these (a trial); default the S&P 500")
    parser.add_argument("--dry-run", action="store_true", help="fetch and print, store nothing")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    key = os.environ.get(KEY_ENV, "").strip()
    user_agent = os.environ.get("SEC_USER_AGENT", "").strip()
    if not key or not user_agent:
        logger.warning("US transcripts skipped: %s and SEC_USER_AGENT are both required", KEY_ENV)
        return 0
    from screener.edgar import EdgarClient
    from storage.supabase_repository import SupabaseRepository

    repo = SupabaseRepository.from_environment("US")
    symbols = args.symbols or sp500_members(repo)
    if not symbols:
        logger.warning("US transcripts skipped: the S&P 500 list could not be read")
        return 0
    try:
        run(
            repo, EdgarClient(user_agent), symbols,
            key=key, today=datetime.now(UTC).date(), budget=args.budget,
            lookback_days=args.lookback_days, dry_run=args.dry_run,
        )
    except Exception as exc:  # noqa: BLE001 -- display evidence: a failure must not fail the workflow
        logger.warning("US transcripts not stored: %s", str(exc).replace(key, "***"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
