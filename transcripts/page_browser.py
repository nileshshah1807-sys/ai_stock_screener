"""An investor page as a browser sees it: its rendered markup and the media it asks for.

Reading a page with a plain request misses two kinds: a page whose player is
built by a script, and a site that refuses anything that is not a browser.
Opening the page in a headless browser answers both. A third kind loads its
player only when the reader opens a row or presses a button, so whatever on
the page is labelled as a call's audio is clicked. Nothing is played or
recorded -- the browser is only watched for the audio file the page requests,
which `transcripts/recording_sources.py` then judges by the same rules as any
other and downloads itself.

Playwright is in the speech lock only, and the plan job of the call-recordings
workflow is the one place this runs. Without it, or without a browser to
launch, a page is simply not rendered.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
#: Long enough for a script to build its player; a page still loading is read as it is.
SETTLE_MILLISECONDS = 6000
_MEDIA_PATH = re.compile(r"\.(?:mp3|m4a|wav|aac|ogg|wma|mp4)$", re.IGNORECASE)
# What a page calls the thing to press: "Earnings Call Q2 Audio", "Concall recording".
_AUDIO_LABEL = re.compile(r"audio|recording|earnings?\s*call|con\W?call|conference\s+call|webcast", re.IGNORECASE)
_QUARTER_LABEL = re.compile(r"(?<![a-z0-9])q([1-4])(?![0-9])", re.IGNORECASE)
#: A label is a few words; a paragraph that mentions a recording is not a control.
MAX_LABEL = 90
MAX_CLICKS = 6
MAX_LABELS_READ = 40
CLICK_SETTLE_MILLISECONDS = 1500


@dataclass(frozen=True)
class RenderedPage:
    url: str
    html: str
    #: Addresses the page asked for as audio or video, whatever they are named.
    media: list[str]
    #: The page's links as (address, text), for looking one page further in.
    links: list[tuple[str, str]] = field(default_factory=list)


def _launch(playwright):
    """A browser: the one named by the environment, the machine's own Chrome, or Playwright's."""
    path = os.getenv("CALL_RECORDING_BROWSER_PATH", "").strip()
    if path:
        return playwright.chromium.launch(executable_path=path, headless=True)
    try:
        # A hosted runner ships Chrome, which saves downloading a browser every run.
        return playwright.chromium.launch(channel="chrome", headless=True)
    except Exception:  # noqa: BLE001 - Playwright raises its own error when Chrome is absent
        return playwright.chromium.launch(headless=True)


def _press_audio_labels(page, quarter: int | None) -> None:
    """Click what the page labels as a call's audio, leaving other quarters' alone."""
    labels = page.get_by_text(_AUDIO_LABEL)
    clicks = 0
    for index in range(min(labels.count(), MAX_LABELS_READ)):
        if clicks >= MAX_CLICKS:
            break
        label = labels.nth(index)
        try:
            text = label.inner_text(timeout=1500).strip()
        except Exception:  # noqa: BLE001 - an element that left the page between the count and the read
            continue
        if not text or len(text) > MAX_LABEL:
            continue
        named = {int(found) for found in _QUARTER_LABEL.findall(text)}
        if quarter and named and quarter not in named:
            continue
        try:
            label.click(timeout=2500, force=True)
        except Exception:  # noqa: BLE001 - hidden, covered or gone: the next label
            continue
        clicks += 1
        page.wait_for_timeout(CLICK_SETTLE_MILLISECONDS)


def render_page(link: str, quarter_end: date | None = None) -> RenderedPage | None:
    """The page at ``link`` after its scripts have run, or None when it cannot be opened.

    ``quarter_end`` says which call is wanted, so that a row labelled with
    another quarter is not opened.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.info("Playwright is not installed; the page is not rendered")
        return None

    media: set[str] = set()

    def note(request) -> None:
        if request.resource_type == "media" or _MEDIA_PATH.search(urlsplit(request.url).path):
            media.add(request.url)

    try:
        with sync_playwright() as playwright:
            browser = _launch(playwright)
            try:
                context = browser.new_context(user_agent=USER_AGENT, locale="en-IN")
                # On the context, not the page: a button may open its file in a new tab.
                context.on("request", note)
                page = context.new_page()
                response = page.goto(link, wait_until="domcontentloaded", timeout=45_000)
                if response is None or response.status >= 400:
                    return None
                page.wait_for_timeout(SETTLE_MILLISECONDS)
                quarter = {6: 1, 9: 2, 12: 3, 3: 4}.get(quarter_end.month) if quarter_end else None
                _press_audio_labels(page, quarter)
                links = page.eval_on_selector_all(
                    "a[href]", "items => items.map(item => [item.href, (item.innerText || '').trim().slice(0, 80)])"
                )
                return RenderedPage(
                    url=page.url,
                    html=page.content(),
                    media=sorted(media),
                    links=[(str(href), str(text)) for href, text in links],
                )
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - a page that will not open is one more page without a recording
        logger.info("The page a notice links to could not be rendered: %s", exc)
        return None


def download_in_browser(url: str, folder: Path, name: str) -> Path | None:
    """The file at ``url`` saved by the browser, or None when it will not serve it.

    For a site that refuses a script's request (403) but serves a browser: the
    site's own page is opened first, for the cookies its bot filter sets, then
    the file is fetched as a same-origin download. Nothing is played.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    parts = urlsplit(url)
    path = folder / f"{name}{Path(parts.path).suffix.lower() or '.mp3'}"
    try:
        with sync_playwright() as playwright:
            browser = _launch(playwright)
            try:
                context = browser.new_context(user_agent=USER_AGENT, locale="en-IN", accept_downloads=True)
                page = context.new_page()
                page.goto(f"{parts.scheme}://{parts.netloc}/", wait_until="domcontentloaded", timeout=45_000)
                with page.expect_download(timeout=120_000) as download:
                    page.evaluate(
                        "href => { const a = document.createElement('a'); a.href = href; a.download = ''; "
                        "document.body.appendChild(a); a.click(); }",
                        url,
                    )
                download.value.save_as(path)
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - a refused file is one more recording not fetched
        logger.info("The browser could not download %s: %s", url, exc)
        path.unlink(missing_ok=True)
        return None
    return path
