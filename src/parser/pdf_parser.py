"""
PDF parsing module using PyMuPDF (fitz).

Extracts text organized by section, along with equations and figure captions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import fitz  # PyMuPDF
except ImportError as e:
    raise ImportError("PyMuPDF is required: pip install pymupdf") from e


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Figure:
    caption: str
    page: int


@dataclass
class Section:
    title: str
    text: str
    equations: list[str] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "text": self.text,
            "equations": self.equations,
            "figures": [{"caption": f.caption, "page": f.page} for f in self.figures],
        }


@dataclass
class ParsedPaper:
    path: str
    title: str
    abstract: str
    sections: list[Section]
    raw_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "title": self.title,
            "abstract": self.abstract,
            "sections": [s.to_dict() for s in self.sections],
        }


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------

# Typical academic section header patterns
_SECTION_HEADER_RE = re.compile(
    r"^(?:"
    r"\d+(?:\.\d+)*\s+[A-Z]"          # "1 Introduction", "2.1 Background"
    r"|[A-Z][A-Z\s]{3,}$"             # ALL CAPS lines like "INTRODUCTION"
    r"|(?:Abstract|Introduction|Related Work|Background|Method(?:ology)?|"
    r"Experiment(?:s|al)?|Results?|Discussion|Conclusion|References?|"
    r"Appendix|Acknowledgements?)\b"
    r")",
    re.MULTILINE,
)

# Equation-like content: contains math symbols, Greek letters, or LaTeX-ish text
_EQUATION_RE = re.compile(
    r"(?:"
    r"[=≈≠<>≤≥±∑∏∫∂∇∈∉⊂⊃∪∩]"       # math operators/symbols
    r"|\\[a-zA-Z]+"                   # LaTeX commands like \alpha
    r"|[αβγδεζηθικλμνξπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΠΡΣΤΥΦΧΨΩ]"  # Greek
    r"|\b[a-z]_\{?\w+\}?"            # subscripts like x_i or x_{ij}
    r"|\b[a-z]\^\{?\w+\}?"           # superscripts like x^2
    r")"
)

_FIGURE_CAPTION_RE = re.compile(
    r"^(?:Fig(?:ure)?\.?\s*\d+|Table\s*\d+)[:\s]",
    re.IGNORECASE | re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

class PDFParser:
    """Parses an academic PDF into structured sections with equations and figures."""

    def __init__(self, equation_density_threshold: float = 0.05):
        """
        Args:
            equation_density_threshold: fraction of chars that must be math-like
                for a text block to be considered an equation block.
        """
        self.eq_threshold = equation_density_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, pdf_path: str | Path) -> ParsedPaper:
        """Parse a PDF file and return a structured ParsedPaper."""
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        doc = fitz.open(str(pdf_path))
        try:
            pages_text = self._extract_pages(doc)
            full_text = "\n".join(pages_text)
            title = self._extract_title(doc, pages_text)
            abstract = self._extract_abstract(full_text)
            sections = self._split_into_sections(full_text, doc)
        finally:
            doc.close()

        return ParsedPaper(
            path=str(pdf_path),
            title=title,
            abstract=abstract,
            sections=sections,
            raw_text=full_text,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_pages(self, doc: fitz.Document) -> list[str]:
        """Extract text from each page."""
        pages = []
        for page in doc:
            text = page.get_text("text")
            pages.append(text)
        return pages

    def _extract_title(self, doc: fitz.Document, pages_text: list[str]) -> str:
        """Heuristically extract the paper title from the first page."""
        if not pages_text:
            return "Unknown Title"

        # Try metadata first
        meta = doc.metadata
        if meta and meta.get("title", "").strip():
            return meta["title"].strip()

        # Fall back: first non-empty line on page 1 that looks title-like
        lines = [ln.strip() for ln in pages_text[0].splitlines() if ln.strip()]
        for line in lines[:10]:
            # Skip very short lines and lines that look like author names / affiliations
            if 10 < len(line) < 200 and not re.match(r"^\d", line):
                return line
        return lines[0] if lines else "Unknown Title"

    def _extract_abstract(self, full_text: str) -> str:
        """Extract the abstract section."""
        # Look for explicit "Abstract" marker
        match = re.search(
            r"\bAbstract\b[:\s\n]+(.*?)(?=\n\s*\n|\b1[\.\s]|\bIntroduction\b)",
            full_text,
            re.DOTALL | re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
        return ""

    def _split_into_sections(self, text: str, doc: fitz.Document) -> list[Section]:
        """Split full text into sections based on header detection."""
        lines = text.splitlines()
        sections: list[Section] = []
        current_title = "Preamble"
        current_lines: list[str] = []

        def flush(title: str, body_lines: list[str]) -> None:
            body = "\n".join(body_lines).strip()
            if body:
                section = self._build_section(title, body)
                sections.append(section)

        for line in lines:
            stripped = line.strip()
            if self._is_section_header(stripped):
                flush(current_title, current_lines)
                current_title = stripped
                current_lines = []
            else:
                current_lines.append(line)

        flush(current_title, current_lines)

        # Attach figure captions to nearest section
        self._attach_figure_captions(sections, doc)

        return sections

    def _is_section_header(self, line: str) -> bool:
        """Return True if the line looks like an academic section header."""
        if not line or len(line) > 120:
            return False
        return bool(_SECTION_HEADER_RE.match(line))

    def _build_section(self, title: str, body: str) -> Section:
        """Build a Section, extracting equations from the body text."""
        equations = self._extract_equations(body)
        return Section(title=title, text=body, equations=equations)

    def _extract_equations(self, text: str) -> list[str]:
        """
        Identify equation-like text blocks.

        Strategy: split into paragraphs; mark those with high math-symbol density
        as equations, plus short lines that are predominantly symbolic.
        """
        equations: list[str] = []
        paragraphs = re.split(r"\n{2,}", text)

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            total_chars = len(para)
            if total_chars == 0:
                continue

            math_chars = len(_EQUATION_RE.findall(para))
            density = math_chars / total_chars

            is_short_symbolic = len(para) < 120 and density > 0.02
            is_dense_math = density >= self.eq_threshold

            if is_dense_math or is_short_symbolic:
                # Deduplicate and avoid capturing full prose paragraphs
                if para not in equations and len(para) < 500:
                    equations.append(para)

        return equations

    def _attach_figure_captions(self, sections: list[Section], doc: fitz.Document) -> None:
        """
        Extract figure/table captions from the document and attach them
        to the section they most likely belong to (simple heuristic: append to last section).
        """
        if not sections:
            return

        for page_num, page in enumerate(doc, start=1):
            text = page.get_text("text")
            for match in _FIGURE_CAPTION_RE.finditer(text):
                # Grab the caption line
                start = match.start()
                end = text.find("\n\n", start)
                caption = text[start: end if end != -1 else start + 300].strip()
                fig = Figure(caption=caption, page=page_num)
                # Attach to the last section (rough heuristic)
                sections[-1].figures.append(fig)
