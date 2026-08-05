"""PDF text extraction with optional OCR fallback for image-only filings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    method: str


def extract_pdf_text(path: Path, min_text_characters: int, enable_ocr: bool, max_pages: int) -> ExtractionResult:
    import pymupdf

    document = pymupdf.open(path)
    try:
        if document.needs_pass:
            raise ValueError("encrypted PDF cannot be processed")
        if len(document) > max_pages:
            raise ValueError(f"PDF has {len(document)} pages; limit is {max_pages}")
        text = "\n".join(page.get_text("text") for page in document)
        if _is_usable_text(text, min_text_characters):
            return ExtractionResult(text, "pymupdf")
        if not enable_ocr:
            raise ValueError("PDF text quality is too poor and OCR is disabled")
        return ExtractionResult(_extract_with_ocr(document), "ocr")
    finally:
        document.close()


def _is_usable_text(text: str, min_text_characters: int) -> bool:
    meaningful_characters = sum(character.isalnum() for character in text)
    return meaningful_characters >= min_text_characters


def _extract_with_ocr(document) -> str:
    try:
        import pymupdf
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("OCR dependencies are unavailable") from exc

    pages: list[str] = []
    for page in document:
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), colorspace=pymupdf.csRGB, alpha=False)
        image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
        pages.append(pytesseract.image_to_string(image))
    return "\n".join(pages)