"""Where BSE filings come from. Yours to write; nothing else in the repo fetches from BSE.

`workers.bse_filings` calls the three functions below and does everything
after them: it keeps the companies listed on BSE alone, parses each document
with the parsers the NSE filings use (BSE's XBRL is SEBI's same taxonomy), and
stores it in the tables the stock page, the Results page, the Shareholding tab,
the bell and the screener already read.

Until they are written each raises ``NotImplementedError`` and the worker logs
that and stores nothing, so the workflow step is safe to leave on. Replacing
this module with a licensed feed later changes nothing downstream.

Times are BSE's local time (IST), without a timezone. ``symbol`` is BSE's
ticker as the bhavcopy prints it (``TckrSymb``, e.g. ``TANFACIND``), not the
scrip code.
"""

from __future__ import annotations

from datetime import date


def results_filings(start: date, end: date) -> list[dict]:
    """Every quarterly results filing BSE disseminated from ``start`` to ``end``.

    One dict per filing, revisions included (a revision has a new ``filing_id``):

    - ``symbol``: str, BSE's ticker
    - ``period_end``: date, the quarter's last day
    - ``consolidated``: bool
    - ``filing_id``: str, unique to this filing
    - ``filed_at``: datetime, when BSE disseminated it
    - ``xbrl_url``: str, the filing's XBRL document
    - ``taxonomy``: str, one of INDAS, NONINDAS, NBFC, BANKING, LI, GI
    - ``company``: str or None
    """
    raise NotImplementedError("write workers/bse_source.results_filings")


def shareholding_filings(start: date, end: date) -> list[dict]:
    """Every shareholding pattern BSE disseminated from ``start`` to ``end``.

    One dict per filing: ``symbol``, ``period_end`` (date), ``filing_id``,
    ``filed_at`` (datetime), ``xbrl_url`` and ``company``, as above.
    """
    raise NotImplementedError("write workers/bse_source.shareholding_filings")


def fetch_document(url: str) -> str | None:
    """The text of one document a filing names, or None when it cannot be had."""
    raise NotImplementedError("write workers/bse_source.fetch_document")
