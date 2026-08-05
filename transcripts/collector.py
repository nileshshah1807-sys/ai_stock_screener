"""NSE corporate-announcement discovery for earnings call transcripts."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from tempfile import TemporaryDirectory
from typing import Any


_INCLUDED_PHRASES = (
    "transcript",
    "conference call transcript",
    "concall transcript",
    "earnings call transcript",
    "analyst meet transcript",
    "investor call transcript",
)
_EXCLUDED_PHRASES = (
    "annual general meeting",
    "extraordinary general meeting",
    "agm transcript",
    "egm transcript",
    "postal ballot",
    "court proceeding",
)


def is_earnings_transcript(record: dict[str, Any]) -> bool:
    text = " ".join(
        str(record.get(key) or "").lower()
        for key in ("desc", "attchmntText")
    )
    return any(phrase in text for phrase in _INCLUDED_PHRASES) and not any(
        phrase in text for phrase in _EXCLUDED_PHRASES
    )


def discover_nse_transcripts(lookback_days: int) -> list[dict[str, Any]]:
    """Fetch a bounded recent NSE window to tolerate delayed scheduled jobs."""
    from nse import NSE

    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)
    with TemporaryDirectory(prefix="nse_discovery_") as download_folder:
        with NSE(download_folder=download_folder, timeout=60, server=False) as nse:
            records = nse.announcements(
                index="equities",
                from_date=datetime.combine(start_date, datetime.min.time()),
                to_date=datetime.combine(end_date, datetime.max.time()),
            )
    return [record for record in records if is_earnings_transcript(record)]


def filing_payload(record: dict[str, Any]) -> dict[str, Any] | None:
    seq_id = str(record.get("seq_id") or "").strip()
    symbol = str(record.get("symbol") or "").strip().upper()
    if not seq_id or not symbol:
        return None
    return {
        "exchange": "NSE",
        "seq_id": seq_id,
        "symbol": symbol,
        "company_name": record.get("sm_name"),
        "announcement_date": _parse_nse_datetime(record.get("an_dt") or record.get("sort_date")),
        "attachment_url": record.get("attchmntFile"),
        "description": " ".join(
            part for part in (str(record.get("desc") or "").strip(), str(record.get("attchmntText") or "").strip())
            if part
        ),
    }


def _parse_nse_datetime(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    for pattern in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, pattern).isoformat()
        except ValueError:
            continue
    return None