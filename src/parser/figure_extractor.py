"""
PDF figure extraction.

Extracts embedded raster images from a PDF, filtering out decorative/tiny ones.
Returns raw image bytes so the caller can send them directly to a vision LLM
without any intermediate text description.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError as e:
    raise ImportError("PyMuPDF is required: pip install pymupdf") from e

_MIN_BYTES = 8_000
_MIN_DIM = 80  # pixels


@dataclass
class ExtractedFigure:
    page: int
    image_bytes: bytes
    width: int
    height: int


class FigureExtractor:
    """Extracts figures from a PDF as raw image bytes."""

    def extract(self, pdf_path: str | Path, max_figures: int = 8) -> list[ExtractedFigure]:
        """
        Return qualifying figures from the PDF, up to max_figures.
        Sorted by area (largest first) so the most prominent diagrams come first.
        """
        pdf_path = Path(pdf_path)
        doc = fitz.open(str(pdf_path))
        seen_xrefs: set[int] = set()
        results: list[ExtractedFigure] = []

        try:
            for page_num, page in enumerate(doc, start=1):
                for img_info in page.get_images(full=True):
                    xref = img_info[0]
                    if xref in seen_xrefs:
                        continue
                    seen_xrefs.add(xref)

                    img = doc.extract_image(xref)
                    w, h = img.get("width", 0), img.get("height", 0)
                    img_bytes = img.get("image", b"")

                    if len(img_bytes) < _MIN_BYTES:
                        continue
                    if w < _MIN_DIM or h < _MIN_DIM:
                        continue

                    results.append(ExtractedFigure(page=page_num, image_bytes=img_bytes, width=w, height=h))
        finally:
            doc.close()

        results.sort(key=lambda f: f.width * f.height, reverse=True)
        return results[:max_figures]
