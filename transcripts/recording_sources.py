"""Where a call's recording can be fetched from when its notice names no audio file.

Half of all "link of recording" notices carry a link straight to the file and
are served by `transcripts/recordings.py` alone. The rest point at the
company's investor page, a shared drive or a video, or at nothing. This module
resolves those, in the order of how much each can be trusted:

1. the notice's own link -- a file behind a redirect, a shared-drive file, the
   one recording an investor page names for this quarter, or the company's own
   video;
2. a channel that publishes every call as a video (`fallback_video`), matched
   on the company's name and the quarter in the video's title.

Every rule here would rather find nothing than the wrong call: an investor
page lists each quarter's recording beside promotional clips, and transcribing
the wrong one would score the wrong call. A call nothing is found for waits for
the filed transcript, as it always did.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import requests

from transcripts.recordings import (
    _AUDIO_PATH,
    _VIDEO_HOSTS,
    DOWNLOADABLE,
    MAX_AUDIO_BYTES,
    MIN_AUDIO_BYTES,
    PAGE,
    USER_AGENT,
    VIDEO,
)

logger = logging.getLogger(__name__)

#: How a source is fetched: an ordinary download, or a video's audio track.
HTTP = "http"
VIDEO_AUDIO = "video"

MAX_PAGE_BYTES = 3_000_000
#: How far back a channel is listed. A season's busiest day is a few hundred calls.
CHANNEL_LISTING = 600


@dataclass(frozen=True)
class RecordingSource:
    """A recording that can be fetched, and what led to it (for the log and the plan)."""

    url: str
    fetch: str
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
_VIDEO_EMBED = re.compile(
    r"""https?://(?:www\.)?(?:youtube(?:-nocookie)?\.com/(?:embed/|watch\?v=)|youtu\.be/)([\w-]{11})""", re.IGNORECASE
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


def _from_page(link: str, quarter_end: date, session: Any) -> RecordingSource | None:
    try:
        response = session.get(link, headers={"User-Agent": USER_AGENT}, timeout=30, stream=True)
    except requests.RequestException as exc:
        logger.info("The page a notice links to could not be read: %s", exc)
        return None
    with response:
        if response.status_code >= 400:
            return None
        content_type = response.headers.get("Content-Type", "").lower()
        if content_type.startswith(("audio/", "video/")) or _AUDIO_PATH.search(urlsplit(response.url).path):
            return RecordingSource(response.url, HTTP, "the link, followed to the file it serves")
        if "html" not in content_type:
            return None
        html = response.raw.read(MAX_PAGE_BYTES, decode_content=True).decode("utf-8", "replace")
    picked = pick_call_file(page_media(html, response.url), quarter_end)
    if picked:
        return RecordingSource(picked, HTTP, "the one recording of this quarter on the linked page")
    # A page built around a single player: one video, or one shared file.
    videos = set(_VIDEO_EMBED.findall(html))
    drives = set(_DRIVE_EMBED.findall(html))
    if len(videos) == 1 and not drives:
        return RecordingSource(
            f"https://www.youtube.com/watch?v={videos.pop()}", VIDEO_AUDIO, "the one video on the linked page"
        )
    if len(drives) == 1 and not videos:
        download = shared_drive_download(drives.pop())
        if download:
            return RecordingSource(download, HTTP, "the one shared file on the linked page")
    return None


def source_from_notice(
    kind: str, link: str | None, quarter_end: date, session: Any = requests
) -> RecordingSource | None:
    """What the notice's best link (`classify_links`) leads to, or None."""
    if not link:
        return None
    if kind in DOWNLOADABLE:
        return RecordingSource(link, HTTP, kind)
    if kind == VIDEO:
        host = urlsplit(link).netloc.lower()
        # A playlist or a channel is every call the company has posted.
        if any(host.endswith(video) for video in _VIDEO_HOSTS) and "list=" not in link and "/@" not in link:
            return RecordingSource(link, VIDEO_AUDIO, "the company's own video")
        return None
    if kind == PAGE:
        download = shared_drive_download(link)
        if download:
            return RecordingSource(download, HTTP, "a shared-drive file")
        return _from_page(link, quarter_end, session)
    return None


# -- 2. a channel that publishes every call -----------------------------------

_LEGAL_WORDS = re.compile(r"\b(?:ltd|limited|company|co|corporation|corp|the)\b\.?")
_TITLE = re.compile(
    r"^(?P<company>.+?)\s+Q(?P<quarter>[1-4])\s+FY\s*(?P<start>\d{4})-(?P<end>\d{2})\s+con\W*call\b",
    re.IGNORECASE,
)


def company_key(name: str | None) -> str:
    """A company's name with its legal form, brackets and punctuation removed."""
    text = re.sub(r"\(.*?\)", " ", (name or "").lower()).replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", _LEGAL_WORDS.sub(" ", text)).strip()


def fallback_video(videos: list[dict[str, Any]], company: str | None, quarter_end: date) -> RecordingSource | None:
    """The channel's video of this company's call for this quarter, or None.

    `videos` is a channel listing, `[{"id", "title"}]`. A title is matched
    whole: the company's name and nothing else before the quarter. Two videos
    that both match are two uploads of something, and neither is taken.
    """
    wanted = company_key(company)
    quarter, year = fiscal_quarter(quarter_end)
    if not wanted:
        return None
    matches = set()
    for video in videos:
        title = _TITLE.match(str(video.get("title") or ""))
        if not title or not video.get("id"):
            continue
        if int(title["quarter"]) != quarter or int(title["start"]) + 1 != year:
            continue
        if company_key(title["company"]) == wanted:
            matches.add(video["id"])
    if len(matches) != 1:
        return None
    return RecordingSource(
        f"https://www.youtube.com/watch?v={matches.pop()}", VIDEO_AUDIO, "a call channel's video"
    )


# -- fetching a video ----------------------------------------------------------

# yt-dlp solves the player's script with whichever of these is installed.
_SCRIPT_RUNTIMES = {"deno": {}, "node": {}}


def list_channel(channel_url: str, limit: int = CHANNEL_LISTING) -> list[dict[str, Any]]:
    """The newest videos of a channel as `[{"id", "title"}]`; empty when it cannot be listed."""
    import yt_dlp

    options = {"extract_flat": True, "playlistend": limit, "quiet": True, "no_warnings": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            listing = downloader.extract_info(f"{channel_url.rstrip('/')}/videos", download=False) or {}
    except Exception as exc:  # noqa: BLE001 - yt-dlp raises its own hierarchy; a listing is optional
        logger.warning("The call channel could not be listed: %s", exc)
        return []
    return [{"id": entry.get("id"), "title": entry.get("title")} for entry in listing.get("entries") or [] if entry]


def download_video_audio(url: str, folder: Path, name: str) -> Path | None:
    """The audio track of a video saved under ``folder``, or None when it was not served."""
    import yt_dlp

    options = {
        "format": "bestaudio/best",
        "outtmpl": str(folder / f"{name}.%(ext)s"),
        "max_filesize": MAX_AUDIO_BYTES,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "js_runtimes": _SCRIPT_RUNTIMES,
    }
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
            path = Path(downloader.prepare_filename(info))
    except Exception as exc:  # noqa: BLE001 - as above; the caller records a failed attempt
        logger.warning("Video audio download failed: %s", exc)
        return None
    if not path.is_file() or path.stat().st_size < MIN_AUDIO_BYTES:
        path.unlink(missing_ok=True)
        return None
    return path
