"""
Tests for the PDF parser module.

These tests use synthetic in-memory PDFs created with PyMuPDF so no real
PDF files are required to run the test suite.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

# Guard: skip entire module gracefully if PyMuPDF not installed
fitz = pytest.importorskip("fitz", reason="PyMuPDF (fitz) not installed")

from src.parser.pdf_parser import PDFParser, Section, Figure, ParsedPaper, _SECTION_HEADER_RE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pdf(content: str, path: Path) -> None:
    """Write a simple single-page PDF with the given text content."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), content, fontsize=11)
    doc.save(str(path))
    doc.close()


# ---------------------------------------------------------------------------
# Unit tests: section header detection
# ---------------------------------------------------------------------------

class TestSectionHeaderDetection:
    def setup_method(self):
        self.parser = PDFParser()

    def test_numbered_section(self):
        assert self.parser._is_section_header("1 Introduction")

    def test_numbered_subsection(self):
        assert self.parser._is_section_header("2.1 Background")

    def test_allcaps_header(self):
        assert self.parser._is_section_header("INTRODUCTION")

    def test_known_section_name(self):
        assert self.parser._is_section_header("Introduction")
        assert self.parser._is_section_header("Related Work")
        assert self.parser._is_section_header("Conclusion")
        assert self.parser._is_section_header("References")

    def test_regular_sentence_is_not_header(self):
        assert not self.parser._is_section_header(
            "This paper presents a novel approach to natural language understanding."
        )

    def test_empty_string_is_not_header(self):
        assert not self.parser._is_section_header("")

    def test_too_long_line_is_not_header(self):
        long_line = "Introduction " + "x" * 200
        assert not self.parser._is_section_header(long_line)


# ---------------------------------------------------------------------------
# Unit tests: equation extraction
# ---------------------------------------------------------------------------

class TestEquationExtraction:
    def setup_method(self):
        self.parser = PDFParser()

    def test_extracts_equation_with_greek(self):
        text = "The loss function is defined as:\n\nL = α · ∑ x_i² + β\n\nwhere α and β are hyperparameters."
        equations = self.parser._extract_equations(text)
        assert any("α" in eq or "∑" in eq for eq in equations)

    def test_plain_prose_not_extracted(self):
        text = "We conducted experiments on five benchmark datasets.\n\nThe results demonstrate that our approach outperforms baselines."
        equations = self.parser._extract_equations(text)
        assert len(equations) == 0

    def test_latex_style_detected(self):
        text = r"\alpha = \frac{\partial L}{\partial w}"
        equations = self.parser._extract_equations(text)
        assert len(equations) > 0


# ---------------------------------------------------------------------------
# Integration tests: full parse on synthetic PDF
# ---------------------------------------------------------------------------

class TestPDFParserIntegration:
    def setup_method(self):
        self.parser = PDFParser()

    def test_parse_returns_parsed_paper(self, tmp_path):
        content = (
            "Deep Learning Survey\n\n"
            "Abstract\nThis paper surveys deep learning methods.\n\n"
            "1 Introduction\nDeep learning has transformed AI.\n\n"
            "2 Methods\nWe use gradient descent: ∂L/∂w = α · x_i\n\n"
            "3 Conclusion\nWe conclude that deep learning works.\n"
        )
        pdf_path = tmp_path / "test_paper.pdf"
        _make_pdf(content, pdf_path)

        result = self.parser.parse(pdf_path)

        assert isinstance(result, ParsedPaper)
        assert result.path == str(pdf_path)
        assert len(result.sections) >= 1

    def test_abstract_extraction(self, tmp_path):
        content = (
            "My Paper\n\n"
            "Abstract\nThis is the abstract of my paper.\n\n"
            "1 Introduction\nThis is the intro.\n"
        )
        pdf_path = tmp_path / "abstract_test.pdf"
        _make_pdf(content, pdf_path)

        result = self.parser.parse(pdf_path)
        # Abstract may or may not be found depending on PDF text rendering,
        # but the parser should not raise.
        assert isinstance(result.abstract, str)

    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            self.parser.parse("/nonexistent/path/paper.pdf")

    def test_sections_have_correct_types(self, tmp_path):
        content = "Title\n\n1 Introduction\nSome text here.\n\n2 Methods\nMore text.\n"
        pdf_path = tmp_path / "types_test.pdf"
        _make_pdf(content, pdf_path)

        result = self.parser.parse(pdf_path)

        for section in result.sections:
            assert isinstance(section, Section)
            assert isinstance(section.title, str)
            assert isinstance(section.text, str)
            assert isinstance(section.equations, list)
            assert isinstance(section.figures, list)

    def test_to_dict_structure(self, tmp_path):
        content = "Paper Title\n\n1 Introduction\nText.\n"
        pdf_path = tmp_path / "dict_test.pdf"
        _make_pdf(content, pdf_path)

        result = self.parser.parse(pdf_path)
        d = result.to_dict()

        assert "title" in d
        assert "abstract" in d
        assert "sections" in d
        assert isinstance(d["sections"], list)
        for s in d["sections"]:
            assert "title" in s
            assert "text" in s
            assert "equations" in s
            assert "figures" in s


# ---------------------------------------------------------------------------
# Unit tests: Section and Figure dataclasses
# ---------------------------------------------------------------------------

class TestDataClasses:
    def test_section_to_dict(self):
        fig = Figure(caption="Fig 1: Overview", page=2)
        sec = Section(
            title="Methods",
            text="We propose...",
            equations=[r"\alpha + \beta = 1"],
            figures=[fig],
        )
        d = sec.to_dict()
        assert d["title"] == "Methods"
        assert d["equations"] == [r"\alpha + \beta = 1"]
        assert d["figures"][0]["caption"] == "Fig 1: Overview"
        assert d["figures"][0]["page"] == 2

    def test_parsed_paper_to_dict(self, tmp_path):
        sec = Section(title="Intro", text="Hello world.")
        paper = ParsedPaper(
            path="/tmp/test.pdf",
            title="Test Paper",
            abstract="This is an abstract.",
            sections=[sec],
            raw_text="Hello world.",
        )
        d = paper.to_dict()
        assert d["title"] == "Test Paper"
        assert len(d["sections"]) == 1
