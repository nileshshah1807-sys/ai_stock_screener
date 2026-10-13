"""Where a call's recording can be fetched from when its notice names no audio file.

Half of all "link of recording" notices carry a link straight to the file and
are served by `transcripts/recordings.py` alone. Many of the rest point at
something that still leads to one file: a link that redirects to it, a
shared-drive file, or an investor page that holds one recording for this
quarter -- told by the file's name, or by the day it was uploaded. A page
that builds its player with a script, or refuses anything but a browser, is
opened in one (`transcripts/page_browser.py`) where that is switched on.
This module resolves those.

Every rule here would rather find nothing than the wrong call: an investor
page lists each quarter's recording beside promotional clips, and transcribing
the wrong one would score the wrong call. A notice whose recording is a video
is not resolved at all -- the video site refuses a hosted runner's address
(measured 13 Oct 2026). A call nothing is found for is looked for as a vendor's
transcript (`transcripts/vendor_transcripts.py`) and otherwise waits for the
filed one.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import requests

from transcripts.page_browser import render_page
from transcripts.recordings import _AUDIO_PATH, DOWNLOADABLE, PAGE, USER_AGENT

logger = logging.getLogger(__name__)

MAX_PAGE_BYTES = 3_000_000

@dataclass(frozen=True)
class RecordingSource:
    """A recording that can be fetched, and what led to it (for the log and the plan)."""

    url: str
    found: str


# -- the quarter a recording belongs to ---------------------------------------


def fiscal_quarter(quarter_end: date) -> tuple[int, int]:
    """(quarter, fiscal year) of a quarter end, for a year that ends in March."""
    quarter = {6: 1, 9: 2, 12: 3, 3: 4}[quarter_end.month]
    return quarter, quarter_end.year + (1 if quarter_end.month >= 4 else 0)


def _names_quarter(text: str, quarter_end: date) -> bool:
    """Whether a file name or title says it is this quarter's: "Q2 FY27", "q2fy2026-27"."""
    quarter, year = fiscal_quarter(quarter_end)
    text = text.lower()
    if not re.search(rf"(?<![a-z0-9])q{quarter}(?![0-9])", text):
        return False
    short, previous = f"{year % 100:02d}", f"{(year - 1) % 100:02d}"
    years = (rf"fy[\W_]*(?:20)?{short}(?![0-9])", rf"(?:20)?{previous}[\W_]{{1,3}}(?:20)?{short}(?![0-9])")
    return any(re.search(pattern, text) for pattern in years)


_OTHER_QUARTER = re.compile(r"(?<![a-z0-9])q[1-4](?![0-9])")
_CALL_WORDS = re.compile(r"con[\W_]*call|earning|analyst|investor|audio|recording")
_PRESS_WORDS = re.compile(r"media|press")


# -- 1. the notice's own link --------------------------------------------------


def shared_drive_download(link: str) -> str | None:
    """The address that serves a shared-drive file itself, not its viewer page."""
    parts = urlsplit(link)
    host = parts.netloc.lower()
    if host.endswith(("drive.google.com", "docs.google.com")):
        match = re.search(r"/d/([\w-]{20,})", parts.path)
        file_id = match.group(1) if match else (parse_qs(parts.query).get("id") or [""])[0]
        if not file_id or "/folders/" in parts.path:
            return None
        # `confirm` skips the page that says a large file was not virus-scanned.
        return f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"
    if host.endswith(("sharepoint.com", "1drv.ms", "onedrive.live.com")):
        if "/:f:/" in parts.path:  # a folder, which may hold every quarter
            return None
        return f"{link}{'&' if parts.query else '?'}download=1"
    return None


_MEDIA_URL = re.compile(
    r"""https?:[^\s"'<>\\]+?\.(?:mp3|m4a|wav|aac|ogg|wma|mp4)(?:\?[^\s"'<>\\]*)?""", re.IGNORECASE
)
_MEDIA_ATTRIBUTE = re.compile(
    r"""(?:src|href|data-src|data-url|file)\s*=\s*["']([^"']+?\.(?:mp3|m4a|wav|aac|ogg|wma|mp4)(?:\?[^"']*)?)["']""",
    re.IGNORECASE,
)
_DRIVE_EMBED = re.compile(r"""https?://(?:drive|docs)\.google\.com/file/d/[\w-]{20,}[^\s"'<>\\]*""", re.IGNORECASE)


def page_media(html: str, base_url: str) -> list[str]:
    """Every audio or video file a page's markup names, as absolute addresses."""
    found = set(_MEDIA_URL.findall(html))
    found.update(urljoin(base_url, match) for match in _MEDIA_ATTRIBUTE.findall(html))
    return sorted(found)


def pick_call_file(candidates: list[str], quarter_end: date) -> str | None:
    """The one file among a page's media that is this quarter's call, or None.

    A file qualifies by its own name. One that names this quarter is taken
    when it is the only such file, leaving aside a press briefing held beside
    the analyst call. Failing that, a lone file with a call's name that names
    no quarter at all is taken -- a page for one call. Anything else is a
    choice between recordings, and is not made.
    """
    named = [(unquote(urlsplit(link).path.rsplit("/", 1)[-1]).lower(), link) for link in candidates]
    this_quarter = [(name, link) for name, link in named if _names_quarter(name, quarter_end)]
    analysts = [item for item in this_quarter if not _PRESS_WORDS.search(item[0])] or this_quarter
    if len(analysts) == 1:
        return analysts[0][1]
    if this_quarter:
        return None
    calls = [(name, link) for name, link in named if _CALL_WORDS.search(name)]
    if len(calls) == 1 and not _OTHER_QUARTER.search(calls[0][0]):
        return calls[0][1]
    return None


#: A recording is uploaded on the day of its call or just before the notice
#: that announces it; a file older than this is an earlier quarter's.
UPLOAD_DAYS_BEFORE = 6
UPLOAD_DAYS_AFTER = 1
#: Smaller than this is a jingle or a clip, not a call.
MIN_CALL_BYTES = 2_000_000
MAX_FILES_ASKED = 25
_AUDIO_NAME = re.compile(r"\.(?:mp3|m4a|wav|aac|ogg|wma)$", re.IGNORECASE)


def uploaded(link: str, referer: str, session: Any) -> tuple[date | None, int | None, str]:
    """When a file was put on its site, its size and its type, as the site's headers say."""
    headers = {"User-Agent": USER_AGENT, "Referer": referer}
    try:
        response = session.head(link, headers=headers, timeout=20, allow_redirects=True)
        if response.status_code >= 400 or "Last-Modified" not in response.headers:
            # Some sites answer HEAD with nothing useful; one byte of the file says the same.
            response = session.get(link, headers={**headers, "Range": "bytes=0-0"}, timeout=20, stream=True)
            response.close()
    except requests.RequestException:
        return None, None, ""
    try:
        modified = parsedate_to_datetime(response.headers.get("Last-Modified", "")).date()
    except (TypeError, ValueError):
        modified = None
    size = response.headers.get("Content-Range", "").rpartition("/")[2] or response.headers.get("Content-Length", "")
    return modified, int(size) if size.isdigit() else None, response.headers.get("Content-Type", "").lower()


def pick_by_upload_date(candidates: list[str], announced: date, referer: str, session: Any) -> str | None:
    """The one audio file among a page's media that was uploaded for this call, or None.

    Many investor pages name their recordings by the conference provider's
    number, which says nothing about the quarter. What does is when the file
    appeared: a page holds one recording per quarter, so a single audio file
    uploaded in the days before the notice is this call's. Audio only -- a
    promotional video is uploaded on any day -- and two such files are a
    choice that is not made.
    """
    earliest = announced - timedelta(days=UPLOAD_DAYS_BEFORE)
    latest = announced + timedelta(days=UPLOAD_DAYS_AFTER)
    recent = []
    for link in candidates[:MAX_FILES_ASKED]:
        modified, size, content_type = uploaded(link, referer, session)
        audio = bool(_AUDIO_NAME.search(urlsplit(link).path)) or content_type.startswith("audio/")
        if audio and modified and earliest <= modified <= latest and (size or 0) >= MIN_CALL_BYTES:
            recent.append(link)
    return recent[0] if len(recent) == 1 else None


def _from_markup(
    html: str, base_url: str, requested: list[str], quarter_end: date, announced: date | None, session: Any, where: str
) -> RecordingSource | None:
    """The recording a page's markup, and the media it asked for, lead to."""
    candidates = sorted({*page_media(html, base_url), *requested})
    picked = pick_call_file(candidates, quarter_end)
    if picked:
        return RecordingSource(picked, f"the one recording of this quarter on {where}")
    if announced:
        picked = pick_by_upload_date(candidates, announced, base_url, session)
        if picked:
            return RecordingSource(picked, f"the one audio file uploaded for this call on {where}")
    # A page built around a single player of one shared file.
    drives = set(_DRIVE_EMBED.findall(html))
    if len(drives) == 1:
        download = shared_drive_download(drives.pop())
        if download:
            return RecordingSource(download, f"the one shared file on {where}")
    return None


def _from_page(
    link: str, quarter_end: date, session: Any, announced: date | None = None, browse: bool = False
) -> RecordingSource | None:
    source = None
    try:
        response = session.get(link, headers={"User-Agent": USER_AGENT}, timeout=30, stream=True)
    except requests.RequestException as exc:
        logger.info("The page a notice links to could not be read: %s", exc)
        response = None
    if response is not None:
        with response:
            content_type = response.headers.get("Content-Type", "").lower()
            if response.status_code < 400:
                if content_type.startswith(("audio/", "video/")) or _AUDIO_PATH.search(urlsplit(response.url).path):
                    return RecordingSource(response.url, "the link, followed to the file it serves")
                if "html" in content_type:
                    html = response.raw.read(MAX_PAGE_BYTES, decode_content=True).decode("utf-8", "replace")
                    source = _from_markup(html, response.url, [], quarter_end, announced, session, "the linked page")
    if source or not browse:
        return source
    # Some pages build their player with a script, and some refuse anything
    # but a browser: the rendered page and the media it asks for say more.
    rendered = render_page(link)
    if rendered is None:
        return None
    return _from_markup(
        rendered.html, rendered.url, rendered.media, quarter_end, announced, session, "the linked page, rendered"
    )


def source_from_notice(
    kind: str,
    link: str | None,
    quarter_end: date,
    session: Any = requests,
    *,
    announced: date | None = None,
    browse: bool = False,
) -> RecordingSource | None:
    """What the notice's best link (`classify_links`) leads to, or None.

    `announced` is the day of the notice, which lets a file be recognised by
    when it was uploaded; `browse` allows a page to be opened in a browser
    when reading it plainly finds nothing.
    """
    if not link:
        return None
    if kind in DOWNLOADABLE:
        return RecordingSource(link, kind)
    if kind == PAGE:
        download = shared_drive_download(link)
        if download:
            return RecordingSource(download, "a shared-drive file")
        return _from_page(link, quarter_end, session, announced, browse)
    return None
