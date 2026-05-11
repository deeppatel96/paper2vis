"""
Manim rendering wrapper.

Writes a Manim scene to a temp file and invokes `manim render` as a subprocess,
returning the path to the rendered .mp4.

Pre-render pipeline:
  1. Inject layout helpers (auto-available to every scene)
  2. Check for LaTeX / deprecated API usage → clear error for fix loop
  3. Run spatial validator → clear error for fix loop
  4. Render
"""

from __future__ import annotations

import functools
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from src.animation.validator import validate

_HELPERS_PATH = Path(__file__).parent / "layout_helpers.py"


@functools.lru_cache(maxsize=1)
def _load_helpers() -> str:
    """Read helper source once, strip imports and module-level docstring."""
    raw = _HELPERS_PATH.read_text(encoding="utf-8")
    lines = raw.splitlines()

    # Remove module docstring (triple-quoted block at top)
    in_docstring = False
    cleaned: list[str] = []
    for ln in lines:
        stripped = ln.strip()
        if not in_docstring and stripped.startswith('"""') and not cleaned:
            in_docstring = True
            if stripped.endswith('"""') and len(stripped) > 3:
                in_docstring = False  # single-line docstring
            continue
        if in_docstring:
            if stripped.endswith('"""'):
                in_docstring = False
            continue
        # Drop top-level import lines
        if stripped.startswith(("from manim import", "import numpy", "import ")):
            continue
        cleaned.append(ln)

    # Collapse leading blank lines
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    return "\n".join(cleaned)


@functools.lru_cache(maxsize=1)
def _find_manim() -> str:
    import shutil
    # Prefer the manim alongside the current Python interpreter
    candidate = Path(sys.executable).parent / "manim"
    if candidate.exists():
        return str(candidate)
    # Common virtualenv / conda locations
    for prefix in [Path.home() / "miniforge3", Path.home() / "miniconda3", Path.home() / "anaconda3"]:
        p = prefix / "bin" / "manim"
        if p.exists():
            return str(p)
    # Fall back to PATH lookup, then bare name
    found = shutil.which("manim")
    return found if found else "manim"


_LATEX_PATCH_TEMPLATE = '''\
# ── LaTeX pipeline patch (tectonic + PyMuPDF instead of latex + dvisvgm) ──
import manim.utils.tex_file_writing as _tfw_mod
import subprocess as _sp
import fitz as _fitz
from pathlib import Path as _PPath

def _tectonic_compile(tex_file, tex_compiler, output_format):
    """Use tectonic to compile .tex → .pdf regardless of what compiler was requested."""
    pdf_out = _PPath(tex_file).with_suffix(".pdf")
    tex_dir = pdf_out.parent
    if not pdf_out.exists():
        cmd = ["__TECTONIC_PATH__",
               "--outfmt", "pdf", "--outdir", str(tex_dir), str(tex_file)]
        cp = _sp.run(cmd, capture_output=True)
        if cp.returncode != 0:
            raise ValueError(
                f"tectonic failed:\\n{cp.stderr.decode()[:400]}"
            )
    return pdf_out

def _pymupdf_to_svg(dvi_file, extension, page=1):
    """Convert PDF → SVG using PyMuPDF (no dvisvgm needed)."""
    pdf_file = _PPath(dvi_file).with_suffix(".pdf")
    svg_file = _PPath(dvi_file).with_suffix(".svg")
    if svg_file.exists():
        return svg_file
    doc = _fitz.open(str(pdf_file))
    pg = doc[page - 1]
    # Scale 4× for crisp paths; Manim normalises sizes from the SVG viewBox
    mat = _fitz.Matrix(4, 4)
    svg_data = pg.get_svg_image(matrix=mat)
    svg_file.write_text(svg_data, encoding="utf-8")
    return svg_file

_tfw_mod.compile_tex = _tectonic_compile
_tfw_mod.convert_to_svg = _pymupdf_to_svg
# ── end LaTeX patch ──
'''


def _build_latex_patch() -> str:
    """Build the LaTeX patch with the resolved tectonic binary path.

    Checks TECTONIC_PATH env var first, then PATH, then common conda locations.
    Returns an empty string if tectonic is not found (Manim falls back to system LaTeX).
    """
    import logging
    import shutil
    tectonic = os.getenv("TECTONIC_PATH") or shutil.which("tectonic")
    if not tectonic:
        for prefix in [Path.home() / "miniforge3", Path.home() / "miniconda3", Path.home() / "anaconda3"]:
            candidate = prefix / "bin" / "tectonic"
            if candidate.exists():
                tectonic = str(candidate)
                break
    if not tectonic:
        logging.getLogger(__name__).warning(
            "tectonic not found; LaTeX patch disabled. "
            "Set TECTONIC_PATH env var to point at the tectonic binary."
        )
        return ""
    return _LATEX_PATCH_TEMPLATE.replace("__TECTONIC_PATH__", tectonic)


def _inject_helpers(code: str) -> str:
    """
    Insert the LaTeX patch + layout helper functions after the import block.
    Finds the last top-level import line and inserts immediately after.
    """
    helpers = _load_helpers()
    lines = code.splitlines()

    last_import = -1
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped.startswith(("import ", "from ")) and "manim" in stripped or \
           stripped.startswith("import numpy"):
            last_import = i

    insert_at = last_import + 1 if last_import >= 0 else 0
    latex_patch = _build_latex_patch()
    patch_lines = ["", latex_patch, "", helpers, ""] if latex_patch else ["", helpers, ""]
    injected = lines[:insert_at] + patch_lines + lines[insert_at:]
    return "\n".join(injected)


_HELPER_NAMES = {
    "node_row", "flow_column", "side_by_side", "connect",
    "connect_curved", "heatmap", "bar_chart", "animate_bars",
}

_COLOR_FIXES = {
    "LIGHT_GREEN": "GREEN_B",
    "LIGHT_BLUE": "BLUE_B",
    "DARK_BLUE": "BLUE_D",
    "LIGHT_GREY": "GREY_B",
    "DARK_GREY": "GREY_D",
    "LIGHT_RED": "RED_B",
    "ShowCreation(": "Create(",
    "GrowArrow(": "Create(",
    "GrowFromCenter(": "FadeIn(",
}


def _static_fix(code: str) -> str:
    """
    Apply deterministic fixes before LLM validation or rendering.
    No LLM call — pure text transforms.
    """
    # 0. Strip decorative Unicode symbols that Python's tokenizer rejects as invalid code tokens.
    #    LLMs insert these (✓ ✗ ★ etc.) in comments or accidentally in code context.
    #    Math symbols used in MathTex (→ ≤ etc.) are intentionally left untouched.
    code = re.sub(r"[✓✗✔✘★◆■●○◇□△▲▼▽☑☐☒✦✧]", "", code)

    # 0b. Auto-convert Text("x_i") → MathTex(r"x_i") for strings containing math notation
    #     (subscripts _, superscripts ^, or LaTeX backslash commands).
    #     Only applies to plain string literals — f-strings are left alone.
    #     Replaces just the Text("content" prefix; remaining kwargs and closing ) are intact.
    _MATH_IN_TEXT = re.compile(r'[_^]|\\[a-zA-Z]')
    # Long non-LaTeX word (5+ letters not preceded by \) = prose, not math
    _PROSE_WORD = re.compile(r'(?<!\\)\b[a-zA-Z]{5,}\b')

    def _maybe_to_mathtex(m: re.Match) -> str:
        prefix = m.group(1) or ""
        content = m.group(2)
        if "f" in prefix:
            return m.group(0)
        if not _MATH_IN_TEXT.search(content):
            return m.group(0)
        # Don't convert prose sentences: if any non-LaTeX word is ≥5 letters,
        # the string is a label/title and should stay as Text for legible rendering.
        if _PROSE_WORD.search(content):
            return m.group(0)
        return f'MathTex(r"{content}"'

    # Double-quoted Text
    code = re.sub(r'\bText\(\s*(r?)"((?:[^"\\]|\\.)*)"', _maybe_to_mathtex, code)
    # Single-quoted Text (rewritten as double-quoted MathTex)
    code = re.sub(r"\bText\(\s*(r?)'((?:[^'\\]|\\.)*)'", _maybe_to_mathtex, code)

    # 0c. Add font_size=24 to bare Text("string") calls with no arguments at all.
    #     Text() defaults to 48pt which is huge; 24 is a sensible body-text default.
    #     Only matches the zero-extra-args form: Text("...") or Text('...')
    code = re.sub(
        r'\bText\((r?"(?:[^"\\]|\\.)*")\)',
        r'Text(\1, font_size=24)',
        code,
    )
    code = re.sub(
        r"\bText\((r?'(?:[^'\\]|\\.)*')\)",
        r'Text(\1, font_size=24)',
        code,
    )

    # 1. Strip helper function redefinitions (LLM occasionally writes them despite the prompt).
    #    Removes every `def <helper_name>(...)` block at any indentation level.
    lines = code.splitlines()
    result: list[str] = []
    skip_until_indent: int | None = None

    for line in lines:
        stripped = line.lstrip()
        current_indent = len(line) - len(stripped)

        if skip_until_indent is not None:
            # Keep skipping until we return to the same or lower indentation level
            # (and the line is non-empty and not a continuation)
            if stripped and current_indent <= skip_until_indent and not stripped.startswith(("#", ")", "]", "}")):
                skip_until_indent = None
                result.append(line)
            # else: skip this line
            continue

        # Check if this line starts a helper definition
        is_helper_def = False
        if stripped.startswith("def "):
            m = re.match(r"def\s+(\w+)\s*\(", stripped)
            if m and m.group(1) in _HELPER_NAMES:
                is_helper_def = True

        if is_helper_def:
            skip_until_indent = current_indent
            # Don't append this line
            continue

        result.append(line)

    code = "\n".join(result)

    # 2. Strip `self.` prefix from helper function calls (LLM writes `self.node_row(...)` etc.)
    for helper in _HELPER_NAMES:
        code = re.sub(rf"\bself\.({re.escape(helper)})\s*\(", r"\1(", code)

    # 3a. Fix deprecated color names and banned API names (simple substitutions).
    for wrong, right in _COLOR_FIXES.items():
        code = code.replace(wrong, right)

    # 3b. Strip invalid kwargs that Manim Mobjects don't accept.
    #    Text() / VGroup() / etc. don't have an 'alignment' parameter.
    code = re.sub(r",?\s*alignment\s*=\s*['\"][^'\"]*['\"]", "", code)

    # 4a. Fix `self.play(obj)` where obj is a raw Mobject class instantiation.
    #    Pattern: self.play(SomeClass(...)) where SomeClass is a known Mobject but not an Animation.
    #    Heuristic: if the argument starts with a capital letter and isn't already wrapped in
    #    Create/FadeIn/Write/etc., wrap it in Create().
    _animation_wrappers = re.compile(
        r"\b(Create|FadeIn|FadeOut|Write|Transform|ReplacementTransform|"
        r"TransformMatchingShapes|FadeTransform|MoveToTarget|Restore|"
        r"ApplyFunction|ApplyMethod|ApplyMatrix|ApplyComplexFunction|"
        r"Indicate|Flash|Circumscribe|DrawBorderThenFill|LaggedStart|"
        r"AnimationGroup|Succession|GrowFromCenter|ShowCreation|"
        r"SpiralIn|Rotate|ScaleInPlace|MaintainPositionRelativeTo)\s*\("
    )
    def _fix_play_args(m: re.Match) -> str:
        inner = m.group(1)
        # Skip if newline in inner — multi-line play() calls have correct syntax already
        if "\n" in inner:
            return m.group(0)
        # If it already contains an animation wrapper, leave it alone
        if _animation_wrappers.search(inner):
            return m.group(0)
        # If it looks like a bare Mobject call (CapitalCase identifier), wrap in Create
        if re.match(r"\s*[A-Z][A-Za-z]+\s*\(", inner):
            return f"self.play(Create({inner.strip()}))"
        return m.group(0)

    code = re.sub(r"self\.play\(([^)]+\([^)]*\))\)", _fix_play_args, code)

    return code


class ManimRenderer:
    """Renders Manim Python source to an .mp4 file."""

    def __init__(self, quality: str = "medium_quality", preview: bool = False):
        self.quality = quality
        self.preview = preview

    # ------------------------------------------------------------------

    def render(self, code: str, output_dir: str | Path) -> Path:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        code = _static_fix(code)
        self._check_syntax(code)
        self._check_banned_apis(code)
        self._check_spatial(code)
        self._check_dynamic(code)

        full_code = _inject_helpers(code)

        with tempfile.NamedTemporaryFile(
            suffix=".py", prefix="manim_scene_", mode="w", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(full_code)
            scene_file = Path(tmp.name)

        try:
            scene_class = self._detect_scene_class(code)
            quality_flag = self._quality_flag()

            cmd = [
                _find_manim(), "render", quality_flag,
                "--output_file", scene_class,
                "--media_dir", str(output_dir),
                str(scene_file), scene_class,
            ]
            if not self.preview:
                cmd.append("--disable_caching")

            manim_bin = _find_manim()
            env = dict(os.environ)
            extra_bins = [
                str(Path(sys.executable).parent),
                str(Path(manim_bin).parent),
            ]
            # Add conda env bin dirs that contain pdflatex / xelatex
            import shutil as _shutil
            for latex_bin in ["pdflatex", "xelatex"]:
                if not _shutil.which(latex_bin):
                    # Search common conda env locations
                    for candidate in [
                        Path.home() / "miniforge3" / "envs" / "paper2vis" / "bin",
                        Path.home() / "miniforge3" / "bin",
                        Path.home() / "miniconda3" / "envs" / "paper2vis" / "bin",
                        Path("/usr/local/texlive/2023/bin/universal-darwin"),
                        Path("/Library/TeX/texbin"),
                    ]:
                        if (candidate / latex_bin).exists():
                            extra_bins.append(str(candidate))
                            break
            env["PATH"] = os.pathsep.join(extra_bins) + os.pathsep + env.get("PATH", "")

            _timeout = int(os.getenv("MANIM_TIMEOUT", "300"))
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=_timeout)
            except subprocess.TimeoutExpired:
                raise RuntimeError(
                    f"Manim render timed out after {_timeout}s. "
                    "The scene may contain an infinite loop or a very long animation duration. "
                    "Reduce total wait() / play() duration or split into smaller scenes."
                )

            if result.returncode != 0:
                raise RuntimeError(
                    f"Manim render failed (exit {result.returncode}).\n"
                    f"STDOUT:\n{result.stdout}\n"
                    f"STDERR:\n{result.stderr}"
                )

            return self._find_output_video(output_dir, scene_class)

        finally:
            scene_file.unlink(missing_ok=True)

    # ------------------------------------------------------------------

    def _check_syntax(self, code: str) -> None:
        """Raise immediately on Python syntax errors so the fix loop gets a clean message."""
        import ast
        try:
            ast.parse(code)
        except SyntaxError as exc:
            raise RuntimeError(
                f"SyntaxError in generated code at line {exc.lineno}: {exc.msg}\n"
                f"Offending text: {exc.text!r}\n\n"
                "Fix the syntax error — check for unmatched brackets, missing commas, "
                "or unclosed parentheses."
            ) from exc

    def _check_banned_apis(self, code: str) -> None:
        """Raise early with a clear message if truly broken APIs are detected."""
        # MathTex/Tex are now allowed — pdflatex is on the PATH via conda env.
        # Only block APIs that don't exist in Manim Community v0.20.

        # Helper redefinitions are now stripped by _static_fix before this runs.

        # Normalize whitespace so multi-space or newline-split calls are still caught
        normalized = re.sub(r"\s+", " ", code)

        deprecated = {
            "ShowCreation(": "Create(",
            "ShowPassingFlash(": "use Create() or Flash()",
            "Pulse(": "use Indicate() or Flash()",
            "GrowFromCenter(": "use FadeIn(scale=0.5)",
            "GrowArrow(": "use Create(Arrow(...))",
            "LIGHT_GREEN": "GREEN_B or GREEN_C",
            "LIGHT_BLUE": "BLUE_B or BLUE_C",
            "DARK_BLUE": "BLUE_D or BLUE_E",
            "LIGHT_GREY": "GREY_B or GREY_C",
            "DARK_GREY": "GREY_D or GREY_E",
            "LIGHT_RED": "RED_A or RED_B",
        }
        found = {k: v for k, v in deprecated.items() if k in normalized}
        if found:
            fixes = ", ".join(f"'{k}' → '{v}'" for k, v in found.items())
            raise RuntimeError(
                f"Code uses deprecated/non-existent Manim APIs: {fixes}."
            )

        # Common wrong API patterns
        undefined_checks = {
            "self.camera.frame": "self.camera.frame requires MovingCameraScene, not Scene. Either change 'Scene' to 'MovingCameraScene' in the class definition, or remove camera moves.",
        }
        found_undef = {k: v for k, v in undefined_checks.items() if k in normalized}
        if found_undef:
            msgs = "; ".join(found_undef.values())
            raise RuntimeError(f"Code uses wrong Scene type: {msgs}")

    def _check_spatial(self, code: str) -> None:
        """Run static spatial validator; raise if issues found."""
        issues = validate(code)
        if issues:
            bullet = "\n  • ".join(issues)
            raise RuntimeError(
                f"Spatial layout issues detected — fix before rendering:\n  • {bullet}\n\n"
                "Key rules:\n"
                "  • Arrow endpoints: use obj.get_right()/get_left()/get_top()/get_bottom() "
                "or the connect(obj_a, obj_b) helper\n"
                "  • Positions: derive from other objects via .next_to(obj, DOWN) or "
                "center + RIGHT*x + UP*y — never hardcode [x, y, z] lists"
            )

    def _check_dynamic(self, code: str) -> None:
        """Raise if the scene has no dynamic transformations — only static reveals.

        Animations that only use FadeIn/Write/Create/LaggedStart teach nothing
        about the mechanism. At least one Transform, ReplacementTransform,
        ValueTracker, always_redraw, or animate.* call is required.
        """
        dynamic_patterns = [
            r"\bTransform\s*\(",
            r"\bReplacementTransform\s*\(",
            r"\bTransformMatchingShapes\s*\(",
            r"\bValueTracker\s*\(",
            r"\balways_redraw\s*\(",
            r"\.animate\.",
            r"\brate_func\s*=",
            r"\binterpolate_color\s*\(",
            r"\bIndicate\s*\(",           # highlight animation
            r"\bFlash\s*\(",             # flash animation
            r"\bCircumscribe\s*\(",      # circumscribe animation
            r"\bFadeIn\s*\(.*scale\s*=", # scale-in is dynamic
        ]
        if not any(re.search(p, code) for p in dynamic_patterns):
            raise RuntimeError(
                "Scene contains no dynamic animations (no Transform, ReplacementTransform, "
                "ValueTracker, always_redraw, or .animate calls). "
                "The animation must show computation changing, not just objects appearing. "
                "Use Transform(src, dst) to morph objects, or ValueTracker + always_redraw "
                "to animate changing values."
            )

    def _detect_scene_class(self, code: str) -> str:
        match = re.search(r"class\s+(\w+)\s*\(.*?Scene.*?\)", code)
        if match:
            return match.group(1)
        raise ValueError("No Scene subclass found in generated Manim code.")

    def _quality_flag(self) -> str:
        return {"low_quality": "-ql", "medium_quality": "-qm", "high_quality": "-qh"}.get(
            self.quality, "-qm"
        )

    def _find_output_video(self, output_dir: Path, scene_class: str) -> Path:
        for candidate in output_dir.rglob("*.mp4"):
            if scene_class in candidate.stem and "partial_movie_files" not in str(candidate):
                return candidate
        mp4_files = sorted(
            (p for p in output_dir.rglob("*.mp4") if "partial_movie_files" not in str(p)),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if mp4_files:
            return mp4_files[0]
        raise FileNotFoundError(
            f"Could not find rendered .mp4 for scene '{scene_class}' under {output_dir}"
        )
