"""
RAG (Retrieval-Augmented Generation) example store for Manim code generation.

Stores curated Manim scene examples labeled by scientific field.
Retrieval uses TF-IDF-style word-overlap scoring — no external embedding service needed.
"""

from __future__ import annotations

import json
import math
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

_EXAMPLES_PATH = Path(__file__).parent.parent.parent / "data" / "rag_examples.json"

# Scientific fields used as labels
FIELDS = [
    "machine_learning",
    "quantum_computing",
    "linear_algebra",
    "calculus",
    "physics",
    "signal_processing",
    "graph_theory",
    "probability",
    "general",
]


@dataclass
class ManimExample:
    field: str
    description: str
    tags: List[str]
    code: str  # just the Scene class body, no imports
    source_url: str = ""  # attribution — e.g. 3b1b GitHub permalink

    def search_text(self) -> str:
        return f"{self.description} {' '.join(self.tags)} {self.field}"


class ExampleStore:
    """Loads and retrieves Manim examples by relevance to a query."""

    def __init__(self, path: Path = _EXAMPLES_PATH):
        self._path = path
        self._examples: List[ManimExample] = []
        self._idf: dict[str, float] = {}
        self._loaded = False
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._loaded:
                return
            if self._path.exists():
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._examples = [ManimExample(**item) for item in raw]
            self._build_idf()
            self._loaded = True

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def _build_idf(self) -> None:
        N = len(self._examples) or 1
        doc_freq: dict[str, int] = {}
        for ex in self._examples:
            for tok in set(self._tokenize(ex.search_text())):
                doc_freq[tok] = doc_freq.get(tok, 0) + 1
        self._idf = {tok: math.log(N / df) for tok, df in doc_freq.items()}

    def _score(self, query_tokens: List[str], ex: ManimExample) -> float:
        doc_tokens = self._tokenize(ex.search_text())
        doc_tf: dict[str, float] = {}
        for tok in doc_tokens:
            doc_tf[tok] = doc_tf.get(tok, 0) + 1
        n = len(doc_tokens) or 1
        score = 0.0
        for tok in query_tokens:
            tf = doc_tf.get(tok, 0) / n
            idf = self._idf.get(tok, 0.0)
            score += tf * idf
        return score

    def retrieve(
        self,
        query: str,
        field: Optional[str] = None,
        k: int = 3,
    ) -> List[ManimExample]:
        """Return top-k examples ranked by relevance to query."""
        self._ensure_loaded()
        if not self._examples:
            return []

        qtoks = self._tokenize(query)
        pool = [ex for ex in self._examples if field is None or ex.field == field]
        if not pool:
            pool = self._examples  # fall back to all fields

        scored = sorted(pool, key=lambda ex: -self._score(qtoks, ex))
        return scored[:k]

    def format_for_prompt(self, examples: List[ManimExample]) -> str:
        """Format retrieved examples as a prompt block."""
        if not examples:
            return ""
        has_3b1b = any("3b1b" in ex.source_url or "3blue1brown" in ex.source_url.lower() for ex in examples)
        style_note = (
            "These are adapted from 3Blue1Brown's actual video code. "
            "Match this visual style: mathematical precision, smooth transitions, "
            "ValueTracker-driven continuous motion, MathTex for all formulas, "
            "clean color-coded labeling, and a title that persists throughout. "
            "NOTE: always specify font_size explicitly — title=34, body=24, annotations=18, tiny=14. "
            "Never use Text() without font_size (defaults to 48pt which is too large).\n"
        ) if has_3b1b else (
            "These working Manim scenes are provided as reference. "
            "Study their patterns — use similar animation sequences, "
            "helper calls, and positioning when appropriate.\n"
        )
        parts = ["<rag_examples>", style_note]
        for i, ex in enumerate(examples, 1):
            src = f" · {ex.source_url}" if ex.source_url else ""
            parts.append(f"--- Example {i} ({ex.field}{src}): {ex.description} ---")
            parts.append("```python")
            parts.append(ex.code.strip())
            parts.append("```\n")
        parts.append("</rag_examples>")
        return "\n".join(parts)

    def add_example(self, example: ManimExample) -> None:
        self._ensure_loaded()
        self._examples.append(example)
        self._build_idf()

    def save(self) -> None:
        self._ensure_loaded()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {"field": e.field, "description": e.description,
             "tags": e.tags, "code": e.code, "source_url": e.source_url}
            for e in self._examples
        ]
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def __len__(self) -> int:
        self._ensure_loaded()
        return len(self._examples)


# Module-level singleton
_store: Optional[ExampleStore] = None


def get_store() -> ExampleStore:
    global _store
    if _store is None:
        _store = ExampleStore()
    return _store
