"""
Manim code generation via LLM.

Three generation modes:
  two_pass  — concept → storyboard → Manim code  (original, highest quality)
  dsl       — concept → validated JSON spec → compiled Manim code (most reliable)
  direct    — concept → Manim code in one shot (fastest)

RAG injection is supported for two_pass and direct modes.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

from src.llm_utils import call_llm, call_llm_vision_bytes

load_dotenv()

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

GenerationMode = str  # "two_pass" | "dsl" | "direct"


class ManimCodeGenerator:
    """Generates runnable Manim scene Python code for a given Concept."""

    def __init__(self, provider: str | None = None, model: str | None = None):
        self.provider = (provider or os.environ.get("CODEGEN_PROVIDER") or os.environ.get("LLM_PROVIDER", "anthropic")).lower()
        default_models = {
            "anthropic": "claude-sonnet-4-6",
            "openai": "gpt-4o",
            "ollama": "llama3.1:8b",
        }
        self.model = (
            model
            or os.environ.get("CODEGEN_MODEL")
            or os.environ.get("LLM_MODEL")
            or default_models.get(self.provider, "llama3.1:8b")
        )
        self._storyboard_template = self._load_prompt(PROMPTS_DIR / "manim_storyboard.txt")
        self._figure_storyboard_template = self._load_prompt(PROMPTS_DIR / "manim_figure_storyboard.txt")
        self._codegen_template = self._load_prompt(PROMPTS_DIR / "manim_codegen.txt")
        self._figure_direct_template = self._load_prompt(PROMPTS_DIR / "manim_figure_direct.txt")
        self._fix_prompt_template = self._load_prompt(PROMPTS_DIR / "fix_code.txt")
        self._visual_diff_template = self._load_prompt(PROMPTS_DIR / "manim_visual_diff.txt")
        self._dsl_template = self._load_prompt(PROMPTS_DIR / "manim_dsl.txt")
        self._direct_template = self._load_prompt(PROMPTS_DIR / "manim_direct.txt")

    # ------------------------------------------------------------------
    # Primary generation entry point
    # ------------------------------------------------------------------

    def generate(
        self,
        concept: "Concept",  # noqa: F821
        figure_context: list[str] | None = None,
        mode: GenerationMode = "two_pass",
        rag_examples: str = "",
    ) -> str:
        """Generate Manim code using the specified mode."""
        if mode == "dsl":
            return self.generate_dsl(concept, rag_examples=rag_examples)
        if mode == "direct":
            return self.generate_direct(concept, rag_examples=rag_examples)
        # Default: two_pass
        storyboard = self._plan(concept, figure_context)
        return self._code_from_storyboard(storyboard, rag_examples=rag_examples)

    def get_storyboard(self, concept: "Concept", figure_context: list[str] | None = None) -> str:
        """Expose the storyboard for logging/debugging."""
        return self._plan(concept, figure_context)

    # ------------------------------------------------------------------
    # DSL mode
    # ------------------------------------------------------------------

    def generate_dsl(
        self,
        concept: "Concept",  # noqa: F821
        storyboard: str = "",
        rag_examples: str = "",
    ) -> str:
        """Generate code via validated JSON spec → DSL compiler.

        Structural errors are impossible since the output is compiled from
        a Pydantic-validated spec rather than free-form Python.
        Falls back to two_pass if JSON parsing fails.
        """
        from src.animation.dsl import DSLCompiler, parse_spec

        shot_list_text = "\n".join(
            f"{i+1}. {beat}" for i, beat in enumerate(concept.shot_list)
        ) if concept.shot_list else "(No shot list — infer from description and source text.)"
        prompt = (
            self._dsl_template
            .replace("{{CONCEPT_NAME}}", concept.name)
            .replace("{{CONCEPT_DESCRIPTION}}", concept.description)
            .replace("{{VISUAL_TYPE}}", concept.visual_type)
            .replace("{{VARIABLES}}", ", ".join(concept.variables) or "N/A")
            .replace("{{SHOT_LIST}}", shot_list_text)
            .replace("{{RAW_TEXT}}", concept.raw_text)
            .replace("{{STORYBOARD}}", storyboard or "(none — generate beats directly from concept)")
            .replace("{{RAG_EXAMPLES}}", rag_examples)
        )
        raw = call_llm(self.provider, self.model, prompt, max_tokens=2048)
        try:
            spec = parse_spec(raw)
            return DSLCompiler().compile(spec)
        except Exception as exc:
            raise RuntimeError(f"DSL spec parse/compile failed: {exc}\nRaw:\n{raw[:500]}") from exc

    # ------------------------------------------------------------------
    # Direct mode
    # ------------------------------------------------------------------

    def generate_direct(
        self,
        concept: "Concept",  # noqa: F821
        rag_examples: str = "",
    ) -> str:
        """Single-pass: concept → Manim code with no storyboard intermediate."""
        shot_list_text = "\n".join(
            f"{i+1}. {beat}" for i, beat in enumerate(concept.shot_list)
        ) if concept.shot_list else "(No shot list — infer from description and source text.)"
        prompt = (
            self._direct_template
            .replace("{{CONCEPT_NAME}}", concept.name)
            .replace("{{CONCEPT_DESCRIPTION}}", concept.description)
            .replace("{{VISUAL_TYPE}}", concept.visual_type)
            .replace("{{VARIABLES}}", ", ".join(concept.variables) or "N/A")
            .replace("{{SHOT_LIST}}", shot_list_text)
            .replace("{{RAW_TEXT}}", concept.raw_text)
            .replace("{{RAG_EXAMPLES}}", rag_examples)
        )
        raw = call_llm(self.provider, self.model, prompt, max_tokens=4096)
        return self._extract_code(raw)

    def generate_from_figure(self, concept: "Concept", figure_bytes: bytes) -> str:
        """Single vision call: figure image → Manim code, no storyboard intermediate."""
        prompt = (
            self._figure_direct_template
            .replace("{{CONCEPT_NAME}}", concept.name)
            .replace("{{CONCEPT_DESCRIPTION}}", concept.description)
            .replace("{{VISUAL_TYPE}}", concept.visual_type)
            .replace("{{VARIABLES}}", ", ".join(concept.variables) or "N/A")
        )
        raw = call_llm_vision_bytes(self.provider, self.model, prompt, [figure_bytes], max_tokens=4096)
        return self._extract_code(raw)

    def get_storyboard_from_figure(self, concept: "Concept", figure_bytes: bytes) -> str:
        """Pass 1 (figure path): vision call produces a precise storyboard from the image."""
        prompt = (
            self._figure_storyboard_template
            .replace("{{CONCEPT_NAME}}", concept.name)
            .replace("{{CONCEPT_DESCRIPTION}}", concept.description)
            .replace("{{VISUAL_TYPE}}", concept.visual_type)
            .replace("{{VARIABLES}}", ", ".join(concept.variables) or "N/A")
        )
        return call_llm_vision_bytes(
            self.provider, self.model, prompt, [figure_bytes], max_tokens=2048
        )

    def code_from_figure(self, storyboard: str, figure_bytes: bytes) -> str:
        """Pass 2 (figure path): codegen sees both the storyboard AND the original figure.

        The image is included so the model can use it as ground truth for exact
        shapes, labels, colors, and layout — not just the text description.
        """
        # Prepend a vision-specific preamble, then reuse the full codegen rules
        preamble = (
            "The image above is a figure extracted directly from an academic paper. "
            "Use it as the visual ground truth — match its exact shapes, labels, colors, "
            "and layout. The storyboard below describes how to animate it; follow it "
            "beat-by-beat but let the image override any ambiguity in the text.\n\n"
        )
        base_prompt = self._codegen_template.replace("{{STORYBOARD}}", storyboard)
        prompt = preamble + base_prompt
        raw = call_llm_vision_bytes(
            self.provider, self.model, prompt, [figure_bytes], max_tokens=4096
        )
        return self._extract_code(raw)

    def fix_code_from_visual_diff(
        self, code: str, concept_name: str, figure_bytes: bytes, rendered_frame_bytes: bytes
    ) -> tuple[str, str]:
        """Visual diff loop: compare paper figure vs rendered frame → targeted fix.

        Returns (fixed_code, diff_report_json_str).
        """
        import json as _json
        prompt = self._visual_diff_template.replace("{{CONCEPT_NAME}}", concept_name)
        raw = call_llm_vision_bytes(
            self.provider, self.model, prompt,
            [figure_bytes, rendered_frame_bytes],
            max_tokens=1024,
        )

        # Extract diff JSON
        import re as _re
        json_match = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, _re.DOTALL)
        if not json_match:
            json_match = _re.search(r"(\{.*\})", raw, _re.DOTALL)

        fix_instruction = ""
        diff_report = raw
        if json_match:
            try:
                data = _json.loads(json_match.group(1))
                fix_instruction = data.get("fix_instruction", "")
                diff_report = json_match.group(0)
            except (_json.JSONDecodeError, KeyError):
                pass

        if not fix_instruction:
            return code, diff_report

        fixed_code = self.apply_instruction(code, fix_instruction)
        return fixed_code, diff_report

    def validate_code(self, code: str) -> str:
        """Static LLM review before the first render attempt.

        Catches issues the prompt rules already forbid but the model sometimes
        ignores: invalid color names, banned animation calls, LaTeX usage, etc.
        Returns corrected code (may be identical if no issues found).
        """
        prompt = (
            "You are a Manim Community v0.18+ code reviewer. "
            "Check the code below for ANY of these issues and fix them:\n\n"
            "1. Invalid color names — only these are valid: "
            "BLUE, BLUE_B, BLUE_C, BLUE_D, GREEN, GREEN_B, GREEN_C, RED, ORANGE, YELLOW, "
            "WHITE, BLACK, GREY, GREY_A, GREY_B, GREY_C, GREY_D, TEAL, TEAL_A, TEAL_B, "
            "PURPLE, PURPLE_A, PURPLE_B, PINK, MAROON, GOLD, GOLD_A, GOLD_B. "
            "Replace any LIGHT_*, DARK_*, LIGHT_RED, LIGHT_BLUE, etc. with valid equivalents.\n"
            "2. Banned animation calls: ShowCreation→Create, Pulse→Indicate, "
            "GrowFromCenter→FadeIn(scale=0.5), GrowArrow→Create(Arrow(...)), "
            "ShowPassingFlash (remove or replace).\n"
            "3. MathTex is allowed and preferred for math — do NOT replace it with Text(). "
            "Only fix MathTex if the LaTeX string itself is malformed (unmatched braces, invalid commands). "
            "DecimalNumber/Integer/Variable → always_redraw(lambda: Text(...)).\n"
            "4. Bare direction vectors in Arrow/Line: Arrow(LEFT*2, RIGHT*3) → "
            "Arrow(obj_a.get_right(), obj_b.get_left()).\n"
            "5. flow_column used for left-to-right layouts — flow_column is VERTICAL only. "
            "Replace with side_by_side([...], [...]) for horizontal box arrangements.\n"
            "6. Undefined variables: LEFT_CENTER/RIGHT_CENTER do not exist in Manim — "
            "replace with e.g. CONTENT_CENTER + LEFT*3. Also check for any other undefined names.\n"
            "7. Scalar color passed to node_row/side_by_side/flow_column/bar_chart — "
            "e.g. colors=BLUE or stage_colors=GREEN must be colors=[BLUE]*n or [BLUE, BLUE, ...].\n"
            "8. self.camera.frame requires MovingCameraScene — change Scene → MovingCameraScene if used.\n"
            "9. DrawBorderThenFill only works on VMobject (Circle, Rectangle, etc.), NOT on VGroup, "
            "list, or layout helper output — replace with FadeIn() or Create() for groups.\n"
            "10. Division by zero risk in rescaling — guard with max(val, 0.001) before dividing.\n"
            "11. self.play(obj) where obj is a raw Mobject (not an animation) — must wrap: "
            "self.play(Create(obj)) or self.play(FadeIn(obj)).\n"
            "12. VGroup has no .index attribute — use list(vgroup) or vgroup[i] for indexing.\n"
            "13. Mobject.__init__ does not accept 'alignment' kwarg — remove it.\n"
            "14. Helper functions node_row/flow_column/side_by_side/connect/heatmap/bar_chart "
            "are auto-injected — NEVER define them yourself, just call them.\n"
            "15. side_by_side() and flow_column() use parameter name 'stage_colors', NOT 'colors'.\n\n"
            "If you find issues, return the corrected code. "
            "If the code is already correct, return it unchanged. "
            "Return ONLY the Python code in ```python ... ``` fences.\n\n"
            f"```python\n{code}\n```"
        )
        raw = call_llm(self.provider, self.model, prompt, max_tokens=4096)
        return self._extract_code(raw)

    def fix_code(self, code: str, error: str) -> str:
        """Return corrected code given a Manim render error."""
        prompt = (
            "The following Manim scene code failed to render with Manim Community v0.18+. "
            "Fix ALL errors shown. MathTex and Tex are supported — do NOT replace them with Text(). "
            "If the error is about LaTeX compilation, fix the LaTeX string itself (escape backslashes, fix braces). "
            "Do NOT use: DecimalNumber, Integer, Variable, get_x_axis_label, get_y_axis_label. "
            "Return ONLY the corrected Python code in ```python ... ``` fences.\n\n"
            f"<error>\n{error[:3000]}\n</error>\n\n"
            f"<broken_code>\n```python\n{code}\n```\n</broken_code>"
        )
        raw = call_llm(self.provider, self.model, prompt, max_tokens=4096)
        return self._extract_code(raw)

    def apply_instruction(self, code: str, instruction: str) -> str:
        """Apply a natural-language edit instruction to existing scene code."""
        prompt = (
            self._fix_prompt_template
            .replace("{{INSTRUCTION}}", instruction)
            .replace("{{CODE}}", code)
        )
        raw = call_llm(self.provider, self.model, prompt, max_tokens=4096)
        return self._extract_code(raw)

    # ------------------------------------------------------------------

    def _plan(self, concept: "Concept", figure_context: list[str] | None = None) -> str:  # noqa: F821
        """Pass 1: expand concept + shot_list into a detailed visual storyboard."""
        shot_list_text = "\n".join(
            f"{i+1}. {beat}" for i, beat in enumerate(concept.shot_list)
        ) if concept.shot_list else "(No shot list provided — infer visually interesting beats from the description and source text.)"

        if figure_context:
            fig_block = (
                "<reference_figures>\n"
                "These figures were extracted directly from the paper. "
                "Use them as visual anchors — match the visualization style and conventions shown when relevant.\n\n"
                + "\n\n".join(figure_context)
                + "\n</reference_figures>"
            )
        else:
            fig_block = ""

        prompt = (
            self._storyboard_template
            .replace("{{CONCEPT_NAME}}", concept.name)
            .replace("{{CONCEPT_DESCRIPTION}}", concept.description)
            .replace("{{VISUAL_TYPE}}", concept.visual_type)
            .replace("{{VARIABLES}}", ", ".join(concept.variables) or "N/A")
            .replace("{{RAW_TEXT}}", concept.raw_text)
            .replace("{{SHOT_LIST}}", shot_list_text)
            .replace("{{FIGURE_CONTEXT}}", fig_block)
        )
        return call_llm(self.provider, self.model, prompt, max_tokens=3000)

    def _code_from_storyboard(self, storyboard: str, rag_examples: str = "") -> str:
        """Pass 2: convert storyboard into runnable Manim code."""
        prompt = (
            self._codegen_template
            .replace("{{STORYBOARD}}", storyboard)
            .replace("{{RAG_EXAMPLES}}", rag_examples)
        )
        raw = call_llm(self.provider, self.model, prompt, max_tokens=4096)
        return self._extract_code(raw)

    # ------------------------------------------------------------------

    def _load_prompt(self, path: Path) -> str:
        if not path.exists():
            raise FileNotFoundError(f"Prompt file not found: {path}")
        return path.read_text(encoding="utf-8")

    def _extract_code(self, raw: str) -> str:
        py_match = re.search(r"```(?:python)?\s*(.*?)```", raw, re.DOTALL)
        if py_match:
            return py_match.group(1).strip()
        if "from manim import" in raw or "class " in raw:
            return raw.strip()
        return raw.strip()
