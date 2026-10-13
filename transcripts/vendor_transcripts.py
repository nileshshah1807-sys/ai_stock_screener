"""A vendor's transcript of a call, for when the company's recording cannot be fetched.

Some sites publish their own transcript of an earnings call within about an
hour of its start, as an ordinary page of a WordPress site whose listing is
public. Where a "link of recording" notice leads to nothing this job can
download, that text lets the call be read the same evening anyway
(`workers/call_recordings.py`).

It is a third party's work, so it is the last resort and is treated as
provisional exactly as a recording is: its document's ``extraction_method``
starts ``vendor:``, the dashboard says where the text came from, and the
transcript the company files replaces it. The site is asked for one listing a
run and one page per call it is needed for, under a name that says who is
asking. `CALL_TRANSCRIPT_VENDOR_URL` (set in the workflow) names the site;
unset, nothing here runs.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import date
from typing import Any
from urllib.parse import urlsplit

import requests

from transcripts.recording_sources import fiscal_quarter

logger = logging.getLogger(__name__)

#: Says who is asking, unlike the browser's name a company's own site is given.
USER_AGENT = "winnow-screener (+https://github.com/nileshshah1807-sys/ai_stock_screener)"
# A season's busiest days are over a hundred calls, and a notice is read for three.
LISTING_PAGES = 4
PAGE_SIZE = 100

# "Alpha Engineering Limited (ALPHAENG) Q2 2027 Earnings Call Transcript": the
# exchange symbol in brackets, then the quarter of a year that ends in March.
_TITLE = re.compile(
    r"\((?P<symbol>[A-Z0-9&_-]+)\)\s+Q(?P<quarter>[1-4])\s+(?P<year>\d{4})\s+Earnings Call", re.IGNORECASE
)
_BLOCK_END = re.compile(r"</(?:p|h[1-6]|li|div|tr)>|<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_NOT_TEXT = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)


def vendor_name(base_url: str) -> str:
    """The site's host, as the transcript's document records where it came from."""
    return urlsplit(base_url).netloc.lower().removeprefix("www.")


def _get(url: str, params: dict[str, Any], session: Any) -> Any:
    response = session.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response.json()


def list_transcripts(base_url: str, session: Any = requests) -> list[dict[str, Any]]:
    """The site's newest transcripts as `[{"id", "title", "link"}]`; empty when it cannot be listed."""
    listing: list[dict[str, Any]] = []
    try:
        for page in range(1, LISTING_PAGES + 1):
            rows = _get(
                f"{base_url.rstrip('/')}/wp-json/wp/v2/transcript",
                {"per_page": PAGE_SIZE, "page": page, "_fields": "id,title,link"},
                session,
            )
            for row in rows:
                title = html.unescape(str((row.get("title") or {}).get("rendered") or ""))
                listing.append({"id": row.get("id"), "title": title, "link": row.get("link")})
            if len(rows) < PAGE_SIZE:
                break
    except (requests.RequestException, ValueError, AttributeError) as exc:
        logger.warning("The transcript vendor could not be listed: %s", exc)
    return listing


def find_transcript(listing: list[dict[str, Any]], symbol: str, quarter_end: date) -> dict[str, Any] | None:
    """The listing's transcript of this company's call for this quarter, or None.

    Matched on the exchange symbol in the title, not the company's name. Two
    that both match are a choice between texts, and neither is taken.
    """
    wanted = (symbol.upper(), *fiscal_quarter(quarter_end))
    matches = []
    for entry in listing:
        title = _TITLE.search(str(entry.get("title") or ""))
        if title and entry.get("id") and (title["symbol"].upper(), int(title["quarter"]), int(title["year"])) == wanted:
            matches.append(entry)
    return matches[0] if len(matches) == 1 else None


def page_text(markup: str) -> str:
    """A transcript page's markup as text, one paragraph or speaker line to a line."""
    text = _BLOCK_END.sub("\n", _NOT_TEXT.sub(" ", markup))
    lines = (re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", line))).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def fetch_transcript(base_url: str, entry: dict[str, Any], session: Any = requests) -> str | None:
    """The text of one listed transcript, or None when the site did not serve it."""
    try:
        row = _get(f"{base_url.rstrip('/')}/wp-json/wp/v2/transcript/{entry['id']}", {"_fields": "content"}, session)
    except (requests.RequestException, ValueError) as exc:
        logger.warning("The vendor's transcript could not be read: %s", exc)
        return None
    content = (row.get("content") or {}) if isinstance(row, dict) else {}
    if content.get("protected"):
        return None
    return page_text(str(content.get("rendered") or "")) or None
