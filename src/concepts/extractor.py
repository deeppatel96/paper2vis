"""
LLM-based concept extraction from parsed paper sections.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

VisualType = Literal[
    "equation_transform",
    "diagram",
    "flow",
    "geometric",
    "graph",
    "timeline",
]

VALID_VISUAL_TYPES: set[str] = {
    "equation_transform", "diagram", "flow", "geometric", "graph", "timeline"
}


@dataclass
class Concept:
    name: str
    description: str
    visual_type: VisualType
    variables: list[str] = field(default_factory=list)
    source_section: str = ""
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "visual_type": self.visual_type,
            "variables": self.variables,
            "source_section": self.source_section,
        }


# ---------------------------------------------------------------------------
# LLM client abstraction
# ---------------------------------------------------------------------------

def _call_anthropic(prompt: str, model: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _call_openai(prompt: str, model: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2048,
    )
    return response.choices[0].message.content or ""


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
        max_concepts_per_section: int = 3,
    ):
        self.provider = provider.lower()
        self.model = model or os.environ.get(
            "LLM_MODEL",
            "claude-opus-4-5" if self.provider == "anthropic" else "gpt-4o",
        )
        self.max_concepts_per_section = max_concepts_per_section
        self._prompt_template = self._load_prompt()

    # ------------------------------------------------------------------

    def extract(self, section: dict[str, Any]) -> list[Concept]:
        """
        Extract concepts from a single section dict.

        Args:
            section: dict with keys: title, text, equations, figures

        Returns:
            List of Concept objects.
        """
        section_text = self._format_section(section)
        if not section_text.strip():
            return []

        prompt = self._prompt_template.replace("{{SECTION_TEXT}}", section_text)
        prompt = prompt.replace("{{MAX_CONCEPTS}}", str(self.max_concepts_per_section))

        raw = self._call_llm(prompt)
        concepts = self._parse_response(raw, section_title=section.get("title", ""))
        return concepts

    def extract_all(self, sections: list[dict[str, Any]]) -> list[Concept]:
        """Extract concepts from all sections, deduplicating by name."""
        seen: set[str] = set()
        all_concepts: list[Concept] = []

        for section in sections:
            title = section.get("title", "")
            # Skip reference/bibliography sections
            if re.search(r"^(References?|Bibliography|Acknowledgements?)$", title, re.I):
                continue

            for concept in self.extract(section):
                key = concept.name.lower().strip()
                if key not in seen:
                    seen.add(key)
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
            # Truncate very long sections to save tokens
            parts.append(text[:3000])
        if section.get("equations"):
            parts.append("\nEquations found in section:")
            for eq in section["equations"][:5]:
                parts.append(f"  {eq}")
        return "\n".join(parts)

    def _call_llm(self, prompt: str) -> str:
        if self.provider == "anthropic":
            return _call_anthropic(prompt, self.model)
        elif self.provider == "openai":
            return _call_openai(prompt, self.model)
        else:
            raise ValueError(f"Unknown provider: {self.provider!r}")

    def _parse_response(self, raw: str, section_title: str) -> list[Concept]:
        """Parse the LLM's JSON response into Concept objects."""
        # Extract JSON from response (LLM may wrap it in markdown code blocks)
        json_str = _extract_json(raw)
        if not json_str:
            return []

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return []

        # Expect {"concepts": [...]}
        items = data if isinstance(data, list) else data.get("concepts", [])
        concepts: list[Concept] = []

        for item in items:
            if not isinstance(item, dict):
                continue
            vtype = item.get("visual_type", "diagram")
            if vtype not in VALID_VISUAL_TYPES:
                vtype = "diagram"

            concepts.append(
                Concept(
                    name=item.get("name", "Unnamed Concept"),
                    description=item.get("description", ""),
                    visual_type=vtype,
                    variables=item.get("variables", []),
                    source_section=section_title,
                    raw_text=item.get("raw_text", ""),
                )
            )

        return concepts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import re as re  # noqa: E402  (needed for extract_all)


def _extract_json(text: str) -> str:
    """Pull the first JSON object or array out of a (possibly markdown-wrapped) string."""
    # Try to find a ```json ... ``` block
    md_match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    if md_match:
        return md_match.group(1)

    # Try to find a bare JSON object or array
    obj_match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if obj_match:
        return obj_match.group(1)

    return ""
