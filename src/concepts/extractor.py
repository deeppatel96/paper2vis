"""
LLM-based concept extraction from parsed paper sections.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

_log = logging.getLogger(__name__)

from dotenv import load_dotenv

from src.llm_utils import call_llm

load_dotenv()

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

VisualType = Literal[
    "equation_transform",
    "geometric",
    "number_flow",
    "weight_update",
    "matrix_op",
    "diagram",
    "flow",
    "graph",
    "timeline",
]

VALID_VISUAL_TYPES: set[str] = {
    "equation_transform", "geometric", "number_flow", "weight_update",
    "matrix_op", "diagram", "flow", "graph", "timeline",
}

_RAW_TEXT_LIMIT = 1500  # chars stored per concept; matches codegen prompt usage


@dataclass
class Concept:
    name: str
    description: str
    visual_type: VisualType
    variables: list[str] = field(default_factory=list)
    source_section: str = ""
    raw_text: str = ""
    shot_list: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "visual_type": self.visual_type,
            "variables": self.variables,
            "source_section": self.source_section,
            "raw_text": self.raw_text,
            "shot_list": self.shot_list,
        }


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


class ConceptExtractor:
    """Extracts visualizable concepts from parsed paper sections using an LLM."""

    def __init__(
        self,
        provider: str = "anthropic",
        model: str | None = None,
        max_concepts_per_section: int = 5,
    ):
        self.provider = provider.lower()
        default_models = {
            "anthropic": "claude-sonnet-4-6",
            "openai": os.environ.get("LLM_MODEL", "gpt-4.1"),
            "ollama": "llama3.1:8b",
        }
        self.model = model or os.environ.get(
            "LLM_MODEL", default_models.get(self.provider, "llama3.1:8b")
        )
        self.max_concepts_per_section = max_concepts_per_section
        self._prompt_template = self._load_prompt()

    # ------------------------------------------------------------------

    def extract(self, section: dict[str, Any], novelty_context: str = "") -> list[Concept]:
        section_text = self._format_section(section)
        if not section_text.strip():
            return []

        prompt = self._prompt_template.replace("{{NOVELTY_CONTEXT}}", novelty_context)
        prompt = prompt.replace("{{SECTION_TEXT}}", section_text)
        prompt = prompt.replace("{{MAX_CONCEPTS}}", str(self.max_concepts_per_section))

        raw = call_llm(self.provider, self.model, prompt, max_tokens=4096)
        source_text = section.get("text", "")[:_RAW_TEXT_LIMIT]
        return self._parse_response(raw, section_title=section.get("title", ""), source_text=source_text)

    def extract_all(self, sections: list[dict[str, Any]], novelty_context: str = "") -> list[Concept]:
        """Extract concepts from all sections, deduplicating by name."""
        seen_keys: list[str] = []
        all_concepts: list[Concept] = []

        for section in sections:
            title = section.get("title", "")
            if re.search(r"^(References?|Bibliography|Acknowledgements?)$", title, re.I):
                continue

            for concept in self.extract(section, novelty_context=novelty_context):
                key = normalize_concept_name(concept.name)
                if not any(names_overlap(key, existing) for existing in seen_keys):
                    seen_keys.append(key)
                    all_concepts.append(concept)

        return all_concepts

    # ------------------------------------------------------------------

    def _load_prompt(self) -> str:
        prompt_path = PROMPTS_DIR / "concept_extraction.txt"
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
        return prompt_path.read_text(encoding="utf-8")

    def _format_section(self, section: dict[str, Any]) -> str:
        parts = [f"Section: {section.get('title', 'Untitled')}"]
        text = section.get("text", "").strip()
        if text:
            parts.append(text[:5000])
        if section.get("equations"):
            parts.append("\nEquations found in section:")
            for eq in section["equations"][:5]:
                parts.append(f"  {eq}")
        return "\n".join(parts)

    def _parse_response(self, raw: str, section_title: str, source_text: str = "") -> list[Concept]:
        json_str = _extract_json(raw)
        if not json_str:
            _log.warning("No JSON found in concept extraction response for section '%s'", section_title)
            return []

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            _log.warning("JSON decode failed for section '%s': %s", section_title, exc)
            return []

        items = data if isinstance(data, list) else data.get("concepts", [])
        concepts: list[Concept] = []
        dropped = 0

        for item in items:
            if not isinstance(item, dict):
                dropped += 1
                continue
            name = item.get("name", "").strip()
            if not name:
                dropped += 1
                continue

            vtype = item.get("visual_type", "diagram")
            if vtype not in VALID_VISUAL_TYPES:
                vtype = "diagram"

            shot_list = item.get("shot_list", [])
            if isinstance(shot_list, list):
                shot_list = [s for s in shot_list if isinstance(s, str)]

            concepts.append(
                Concept(
                    name=name,
                    description=item.get("description", ""),
                    visual_type=vtype,
                    variables=item.get("variables", []),
                    source_section=section_title,
                    raw_text=source_text,
                    shot_list=shot_list,
                )
            )

        if dropped:
            _log.warning("Dropped %d malformed concept item(s) for section '%s'", dropped, section_title)

        return concepts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_concept_name(name: str) -> str:
    stopwords = {"the", "a", "an", "of", "in", "for", "and", "or", "with", "on", "via"}
    tokens = re.sub(r"[^a-z0-9\s]", "", name.lower()).split()
    return " ".join(t for t in tokens if t not in stopwords)


def names_overlap(a: str, b: str, threshold: float = 0.6) -> bool:
    set_a = set(a.split())
    set_b = set(b.split())
    if not set_a or not set_b:
        return False
    return len(set_a & set_b) / max(len(set_a), len(set_b)) >= threshold


def _extract_json(text: str) -> str:
    """Robustly extract a JSON object or array from an LLM response.

    Tries multiple strategies in order:
    1. Direct parse (LLM returned only JSON)
    2. Fenced code block  ```json ... ```
    3. Slice from first [ to last ] (array) or first { to last } (object)
    4. Greedy regex as last resort
    """
    text = text.strip()

    # 1. Direct parse
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    # 2. Fenced code block
    md_match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    if md_match:
        candidate = md_match.group(1)
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # 3. Slice from first bracket to last matching bracket
    for open_ch, close_ch in [("[", "]"), ("{", "}")]:
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start != -1 and end > start:
            candidate = text[start:end + 1]
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass

    # 4. Greedy regex fallback
    obj_match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if obj_match:
        return obj_match.group(1)

    return ""
