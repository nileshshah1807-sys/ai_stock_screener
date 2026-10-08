"""Follow a cover letter to the transcript it points at.

A company may file the transcript itself, or a one-page letter saying the
transcript "is available on the below link". The letter passes every length
check a short call would and was being stored and scored as the call. This
module recognises the letter, follows its links -- the PDF's own hyperlinks
first, then URLs printed in the text, then one hop through an investor page --
and accepts a document only if it reads like a call held around the filing
date. A wrong document is worse than none: with nothing found, the filing is
left for the next run and the company goes unscored.
"""

from __future__ import annotations

import contextlib
import ipaddress
import logging
import re
import socket
from datetime import date, timedelta
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from transcripts.cleaner import clean_transcript_text
from transcripts.extractor import ExtractionResult, extract_pdf_text

logger = logging.getLogger(__name__)

# The shortest genuine call stored is about 15,000 characters; the longest
# cover letter about 5,000.
COVER_LETTER_MAX_CHARACTERS = 6000
TRANSCRIPT_MIN_CHARACTERS = 8000
MAX_DOWNLOAD_BYTES = 40 * 1024 * 1024
MAX_CANDIDATES = 8
# An investor page lists every quarter's transcript; this quarter's is found by
# its date, so more of them are opened.
MAX_PAGE_CANDIDATES = 20
# A transcript must be filed within five working days of the call; the window
# allows a late filing and a letter dated a day ahead of the exchange stamp.
CALL_DATE_WINDOW_DAYS = (45, 2)
REQUEST_TIMEOUT_SECONDS = 30
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)

_TRANSCRIPT_WORDS = re.compile(
    r"transcript|con[\s_-]?call|earnings?[\s_-]?call|conference[\s_-]?call|analyst", re.IGNORECASE
)
_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"')\]]+", re.IGNORECASE)
_HREF = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_SPEAKER_TURN = re.compile(r"^[A-Z][A-Za-z .,'()&/-]{1,60}:", re.MULTILINE)
_CALL_WORDS = re.compile(r"\b(?:moderator|operator|question[- ]and[- ]answer|q&a session)\b", re.IGNORECASE)

_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
            ("may",), ("june", "jun"), ("july", "jul"), ("august", "aug"),
            ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
            ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DAY_MONTH_YEAR = re.compile(
    rf"\b(\d{{1,2}})(?:\s*(?:st|nd|rd|th))?[\s,.-]+({_MONTH})[a-z]*[\s,.-]+(\d{{4}})\b", re.IGNORECASE
)
_MONTH_DAY_YEAR = re.compile(
    rf"\b({_MONTH})[a-z]*[\s.-]+(\d{{1,2}})(?:\s*(?:st|nd|rd|th))?[\s,.-]+(\d{{4}})\b", re.IGNORECASE
)
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")


def is_cover_letter(text: str) -> bool:
    """Too short to be a call. Whether a longer text *is* one is a separate test."""
    return len(text) < COVER_LETTER_MAX_CHARACTERS


def looks_like_call_transcript(text: str) -> bool:
    """Long, and structured as people taking turns to speak.

    Rejects the documents a cover letter also links to: the results
    presentation, the press release, the annual report.
    """
    if len(text) < TRANSCRIPT_MIN_CHARACTERS:
        return False
    return len(_SPEAKER_TURN.findall(text)) >= 12 or len(_CALL_WORDS.findall(text)) >= 4


def dates_in(text: str) -> list[date]:
    """Calendar dates written out in ``text``, in the order they appear."""
    found: list[tuple[int, date]] = []

    def add(position, year, month, day):
        with contextlib.suppress(ValueError):
            found.append((position, date(int(year), int(month), int(day))))

    for match in _DAY_MONTH_YEAR.finditer(text):
        add(match.start(), match.group(3), _MONTHS[match.group(2).lower()], match.group(1))
    for match in _MONTH_DAY_YEAR.finditer(text):
        add(match.start(), match.group(3), _MONTHS[match.group(1).lower()], match.group(2))
    for match in _NUMERIC_DATE.finditer(text):
        # Indian filings write day first.
        add(match.start(), match.group(3), match.group(2), match.group(1))
    return [value for _, value in sorted(found, key=lambda item: item[0])]


def held_near(text: str, filed_on: date | None) -> bool:
    """Whether the opening of ``text`` dates the call to just before the filing.

    An investor page lists every quarter's transcript; this is what keeps last
    quarter's from being taken for this one. With no filing date there is
    nothing to check against and the document is refused.
    """
    if filed_on is None:
        return False
    earliest = filed_on - timedelta(days=CALL_DATE_WINDOW_DAYS[0])
    latest = filed_on + timedelta(days=CALL_DATE_WINDOW_DAYS[1])
    return any(earliest <= value <= latest for value in dates_in(text[:4000]))


def _tidy(url: str) -> str:
    url = url.strip().rstrip(".,;")
    return f"https://{url}" if url.lower().startswith("www.") else url


def candidate_links(pdf_path: Path) -> list[str]:
    """Links in a cover letter, most likely the transcript first."""
    import pymupdf

    document = pymupdf.open(pdf_path)
    try:
        annotated = [link.get("uri") or "" for page in document for link in page.get_links()]
        text = "\n".join(page.get_text("text") for page in document)
    finally:
        document.close()
    # A long URL is printed across two lines; rejoin a line that ends inside one.
    joined = re.sub(r"((?:https?://|www\.)\S*[-/_%.=&?])\n(?=\S)", r"\1", text)
    printed = _URL.findall(joined)
    links = list(dict.fromkeys(_tidy(url) for url in [*annotated, *printed] if url))
    links = [url for url in links if urlsplit(url).scheme in {"http", "https"}]

    def order(url: str) -> tuple[int, int]:
        is_pdf = ".pdf" in url.lower()
        named = bool(_TRANSCRIPT_WORDS.search(url))
        return (0 if is_pdf and named else 1 if is_pdf else 2 if named else 3, links.index(url))

    return sorted(links, key=order)


def _is_public_host(url: str) -> bool:
    """Whether ``url`` resolves only to public addresses.

    The URL comes from a document anyone can file. It must not be able to make
    the worker call the runner's own network or a cloud metadata address.
    """
    host = urlsplit(url).hostname
    if not host:
        return False
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    return bool(addresses) and all(ipaddress.ip_address(address).is_global for address in addresses)


def _fetch(url: str, session) -> tuple[bytes, str] | None:
    """``(body, final_url)`` for a public http(s) URL, or None."""
    current = url
    for _ in range(5):
        if urlsplit(current).scheme not in {"http", "https"} or not _is_public_host(current):
            return None
        response = session.get(
            current,
            headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.5"},
            timeout=REQUEST_TIMEOUT_SECONDS,
            stream=True,
            allow_redirects=False,
        )
        try:
            if response.is_redirect and response.headers.get("location"):
                # Followed by hand so every hop passes the public-host check.
                current = urljoin(current, response.headers["location"])
                continue
            if response.status_code != 200:
                return None
            body = bytearray()
            for block in response.iter_content(64 * 1024):
                body.extend(block)
                if len(body) > MAX_DOWNLOAD_BYTES:
                    return None
            return bytes(body), current
        finally:
            response.close()
    return None


def pdf_links_on_page(html: str, base_url: str) -> list[str]:
    """PDF links on an investor page whose address or label names a transcript."""
    links = []
    for href, label in _HREF.findall(html):
        url = urljoin(base_url, unescape(href.strip()))
        if ".pdf" not in url.lower():
            continue
        if _TRANSCRIPT_WORDS.search(url) or _TRANSCRIPT_WORDS.search(re.sub(r"<[^>]+>", " ", label)):
            links.append(url)
    return list(dict.fromkeys(links))


def _transcript_from_pdf(body: bytes, directory: Path, filed_on, min_characters, enable_ocr, max_pages):
    if body[:5] != b"%PDF-":
        return None
    path = directory / "linked_transcript.pdf"
    path.write_bytes(body)
    try:
        extracted = extract_pdf_text(path, min_characters, enable_ocr, max_pages)
    except Exception as exc:  # noqa: BLE001 - an unreadable candidate is just not the transcript
        logger.info("Linked PDF could not be read: %s", exc)
        return None
    text = clean_transcript_text(extracted.text)
    # The date is read from the raw text: it is printed at the head of every
    # page, and the cleaner removes a line repeated like that as a header.
    if not looks_like_call_transcript(text) or not held_near(extracted.text, filed_on):
        return None
    return ExtractionResult(text, f"linked-{extracted.method}")


def fetch_linked_transcript(
    cover_letter: Path,
    directory: Path,
    filed_on: date | None,
    *,
    min_characters: int,
    enable_ocr: bool,
    max_pages: int,
    session=None,
) -> tuple[ExtractionResult, str] | None:
    """The transcript a cover letter links to, as ``(extraction, url)``, or None.

    The returned text is already cleaned.
    """
    import requests

    session = session or requests.Session()
    pages: list[tuple[str, str]] = []

    def attempt(url):
        try:
            fetched = _fetch(url, session)
        except requests.RequestException as exc:
            logger.info("Linked document %s not fetched: %s", url, exc)
            return None
        if fetched is None:
            return None
        body, final_url = fetched
        if body[:5] != b"%PDF-":
            pages.append((body[:2_000_000].decode("utf-8", errors="replace"), final_url))
            return None
        found = _transcript_from_pdf(body, directory, filed_on, min_characters, enable_ocr, max_pages)
        return (found, final_url) if found else None

    for url in candidate_links(cover_letter)[:MAX_CANDIDATES]:
        result = attempt(url)
        if result:
            return result
    # One hop: the letter named the investor page rather than the file.
    for html, base_url in list(pages):
        for url in pdf_links_on_page(html, base_url)[:MAX_PAGE_CANDIDATES]:
            result = attempt(url)
            if result:
                return result
    return None
