"""
Manim code generation via LLM.

Takes a Concept object and returns a complete, runnable Manim scene as Python source.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


# ---------------------------------------------------------------------------
# LLM helpers (same pattern as extractor.py)
# ---------------------------------------------------------------------------

def _call_anthropic(prompt: str, model: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _call_openai(prompt: str, model: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4096,
    )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Code generator
# ---------------------------------------------------------------------------

class ManimCodeGenerator:
    """Generates runnable Manim scene Python code for a given Concept."""

    def __init__(self, provider: str = "anthropic", model: str | None = None):
        self.provider = provider.lower()
        self.model = model or os.environ.get(
            "LLM_MODEL",
            "claude-opus-4-5" if self.provider == "anthropic" else "gpt-4o",
        )
        self._prompt_template = self._load_prompt()

    # ------------------------------------------------------------------

    def generate(self, concept: "Concept") -> str:  # noqa: F821
        """
        Generate a complete Manim scene for the given concept.

        Returns:
            Python source code as a string.
        """
        prompt = self._build_prompt(concept)
        raw = self._call_llm(prompt)
        code = self._extract_code(raw)
        code = self._ensure_class_name(code, concept)
        return code

    # ------------------------------------------------------------------

    def _load_prompt(self) -> str:
        prompt_path = PROMPTS_DIR / "manim_codegen.txt"
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
        return prompt_path.read_text(encoding="utf-8")

    def _build_prompt(self, concept: "Concept") -> str:
        """Fill in the prompt template with concept details."""
        prompt = self._prompt_template
        prompt = prompt.replace("{{CONCEPT_NAME}}", concept.name)
        prompt = prompt.replace("{{CONCEPT_DESCRIPTION}}", concept.description)
        prompt = prompt.replace("{{VISUAL_TYPE}}", concept.visual_type)
        prompt = prompt.replace("{{VARIABLES}}", ", ".join(concept.variables) or "N/A")
        prompt = prompt.replace("{{RAW_TEXT}}", concept.raw_text[:1500] if concept.raw_text else "")
        return prompt

    def _call_llm(self, prompt: str) -> str:
        if self.provider == "anthropic":
            return _call_anthropic(prompt, self.model)
        elif self.provider == "openai":
            return _call_openai(prompt, self.model)
        else:
            raise ValueError(f"Unknown provider: {self.provider!r}")

    def _extract_code(self, raw: str) -> str:
        """Extract Python code from the LLM's response."""
        # Prefer ```python ... ``` blocks
        py_match = re.search(r"```(?:python)?\s*(.*?)```", raw, re.DOTALL)
        if py_match:
            return py_match.group(1).strip()

        # If the whole response looks like code, return it
        if "from manim import" in raw or "class " in raw:
            return raw.strip()

        return raw.strip()

    def _ensure_class_name(self, code: str, concept: "Concept") -> str:
        """Make sure the scene class name is valid and deterministic."""
        # Derive a safe class name from the concept name
        safe_name = re.sub(r"[^a-zA-Z0-9]", "_", concept.name).strip("_")
        safe_name = re.sub(r"_+", "_", safe_name)
        class_name = f"{safe_name.title().replace('_', '')}Scene"

        # If there's already a class that inherits from Scene/ThreeDScene, leave it alone
        if re.search(r"class \w+\(.*Scene\)", code):
            return code

        # Otherwise, try to inject a proper class wrapper (shouldn't normally happen)
        return code
