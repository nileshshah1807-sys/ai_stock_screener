"""The ``nse`` package's client, pointed at NSE's current host.

NSE moved www.nseindia.com to www.nseindia.in (301 on every path, seen 13 Nov
2026 evening). nse 4.0.1 does not follow redirects, so its cookie request
failed and every NSE() raised ConnectionError. Import ``NSE`` from here, never
from ``nse``.

shortcut: patches the three places nse 4.0.1 names the host; drop it when the
lock moves to nse>=5.1.3, which has the new host but no ``boardMeetings``,
``equityBhavcopy`` or ``server=``.
"""

from __future__ import annotations

import json

from nse import NSE, transport

HOST = "https://www.nseindia.in"

NSE.base_url = f"{HOST}/api"


def _set_cookies(self):
    # Before the first request, which Transport.__init__ sends inside NSE.__init__.
    self._session.headers["Referer"] = f"{HOST}/get-quotes/equity?symbol=HDFCBANK"
    cookies = self.request(f"{HOST}/option-chain").cookies
    self.cookie_path.write_text(json.dumps(dict(cookies)))
    return cookies


# The httpx transport only: the requests one (unused here) follows the redirect itself.
transport.Transport._setCookies = _set_cookies

__all__ = ["HOST", "NSE"]
