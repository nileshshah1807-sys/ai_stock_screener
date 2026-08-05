from datetime import datetime
from pathlib import Path
import json
import time

from nse import NSE


DOWNLOAD_DIR = Path("nse_transcripts")
DOWNLOAD_DIR.mkdir(exist_ok=True)

METADATA_FILE = DOWNLOAD_DIR / "transcripts.jsonl"


def is_transcript(record: dict) -> bool:
    description = str(record.get("desc") or "").lower()
    attachment_text = str(record.get("attchmntText") or "").lower()

    text = f"{description} {attachment_text}"

    # Transcript must be explicitly mentioned.
    if "transcript" not in text:
        return False

    # Exclude unrelated transcript types if any appear.
    excluded_phrases = (
        "postal ballot",
        "annual general meeting",
        "extraordinary general meeting",
        "agm transcript",
        "egm transcript",
    )

    if any(phrase in text for phrase in excluded_phrases):
        return False

    return True


def save_metadata(record: dict, saved_path: str) -> None:
    metadata = {
        "seq_id": record.get("seq_id"),
        "symbol": record.get("symbol"),
        "company_name": record.get("sm_name"),
        "isin": record.get("sm_isin"),
        "description": record.get("desc"),
        "announcement_text": record.get("attchmntText"),
        "announcement_date": record.get("an_dt"),
        "sort_date": record.get("sort_date"),
        "source_url": record.get("attchmntFile"),
        "file_size": record.get("attFileSize"),
        "local_path": str(saved_path),
    }

    with METADATA_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(metadata, ensure_ascii=False) + "\n")


with NSE(
    download_folder=DOWNLOAD_DIR,
    server=False,
    timeout=60,
) as nse:
    announcements = nse.announcements(
        index="equities",
        from_date=datetime(2026, 8, 1),
        to_date=datetime(2026, 8, 5),
    )

    transcripts = [
        record
        for record in announcements
        if is_transcript(record)
    ]

    print(f"Total announcements: {len(announcements)}")
    print(f"Probable transcripts: {len(transcripts)}")

    for number, record in enumerate(transcripts, start=1):
        symbol = record.get("symbol", "UNKNOWN")
        company = record.get("sm_name", "Unknown Company")
        pdf_url = record.get("attchmntFile")

        print()
        print(f"[{number}/{len(transcripts)}] {symbol}")
        print(f"Company: {company}")
        print(f"Description: {record.get('desc')}")
        print(f"Announcement: {record.get('attchmntText')}")
        print(f"PDF: {pdf_url}")

        if not pdf_url:
            print("Skipped: attachment URL missing")
            continue

        if ".pdf" not in pdf_url.lower():
            print("Skipped: attachment is not a PDF")
            continue

        try:
            saved_path = nse.download_document(pdf_url)
            save_metadata(record, saved_path)

            print(f"Downloaded: {saved_path}")

        except Exception as exc:
            print(f"Failed: {type(exc).__name__}: {exc}")

            if "403" in str(exc) or "429" in str(exc):
                print("Access rejected or rate limited. Stopping.")
                break

        time.sleep(3)