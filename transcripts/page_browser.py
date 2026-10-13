"""An investor page as a browser sees it: its rendered markup and the media it asks for.

Reading a page with a plain request misses two kinds: a page whose player is
built by a script, and a site that refuses anything that is not a browser.
Opening the page in a headless browser answers both, and nothing is played or
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
from dataclasses import dataclass
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
#: Long enough for a script to build its player; a page still loading is read as it is.
SETTLE_MILLISECONDS = 6000
_MEDIA_PATH = re.compile(r"\.(?:mp3|m4a|wav|aac|ogg|wma|mp4)$", re.IGNORECASE)


@dataclass(frozen=True)
class RenderedPage:
    url: str
    html: str
    #: Addresses the page asked for as audio or video, whatever they are named.
    media: list[str]


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


def render_page(link: str) -> RenderedPage | None:
    """The page at ``link`` after its scripts have run, or None when it cannot be opened."""
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
                page = browser.new_context(user_agent=USER_AGENT, locale="en-IN").new_page()
                page.on("request", note)
                response = page.goto(link, wait_until="domcontentloaded", timeout=45_000)
                if response is None or response.status >= 400:
                    return None
                page.wait_for_timeout(SETTLE_MILLISECONDS)
                return RenderedPage(url=page.url, html=page.content(), media=sorted(media))
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - a page that will not open is one more page without a recording
        logger.info("The page a notice links to could not be rendered: %s", exc)
        return None
