"""
paper2vis main pipeline.

Orchestrates: PDF parse → concept extraction → Manim code generation → rendering.

Usage:
    python -m src.pipeline run papers/mypaper.pdf [--output output/run] [--provider anthropic]
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

load_dotenv()

from src.parser.pdf_parser import PDFParser, ParsedPaper
from src.parser.figure_extractor import FigureExtractor, ExtractedFigure
from src.concepts.extractor import ConceptExtractor, Concept, normalize_concept_name, names_overlap
from src.animation.codegen import ManimCodeGenerator
from src.animation.renderer import ManimRenderer
from src.animation.critic import ManimCritic

console = Console()
app = typer.Typer(help="paper2vis: turn academic papers into animations.", invoke_without_command=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _actionable_error(exc_str: str, max_chars: int = 2000) -> str:
    """Extract the most actionable portion of a Manim error for the fix LLM."""
    lines = exc_str.splitlines()
    error_lines: list[str] = []
    in_traceback = False
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("Traceback (most recent call last"):
            in_traceback = True
            error_lines = [ln]
        elif in_traceback:
            error_lines.append(ln)
            if re.match(r"^\s*\w+Error\b|\w+Exception\b", stripped):
                in_traceback = False
        elif re.match(r"^\s*\w+(Error|Exception)\b", stripped):
            error_lines.append(ln)
    if error_lines:
        return "\n".join(error_lines)[:max_chars]
    return exc_str[:max_chars]


# ---------------------------------------------------------------------------
# Pipeline class
# ---------------------------------------------------------------------------

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": os.environ.get("LLM_MODEL", "gpt-4.1"),
    "ollama": "llama3.1:8b",
}


class Pipeline:
    """End-to-end paper-to-visualization pipeline."""

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        codegen_provider: str | None = None,
        codegen_model: str | None = None,
        max_concepts: int = 10,
        render_quality: str = "medium_quality",
        skip_render: bool = False,
        use_figure_context: bool = False,
    ):
        self.provider = provider or os.environ.get("LLM_PROVIDER", "anthropic")
        self.model = model or os.environ.get(
            "LLM_MODEL",
            DEFAULT_MODELS.get(self.provider, "llama3.1:8b"),
        )
        self.codegen_provider = (
            codegen_provider or os.environ.get("CODEGEN_PROVIDER") or self.provider
        )
        self.codegen_model = (
            codegen_model
            or os.environ.get("CODEGEN_MODEL")
            or DEFAULT_MODELS.get(self.codegen_provider, self.model)
        )

        self.max_concepts = max_concepts
        self.render_quality = render_quality
        self.skip_render = skip_render
        self.use_figure_context = use_figure_context

        self.parser = PDFParser()
        self.extractor = ConceptExtractor(provider=self.provider, model=self.model)
        self.codegen = ManimCodeGenerator(provider=self.codegen_provider, model=self.codegen_model)
        self.renderer = ManimRenderer(quality=render_quality)
        self.critic = ManimCritic(provider=self.codegen_provider, model=self.codegen_model)
        self.figure_extractor = FigureExtractor()

    def run(self, pdf_path: str | Path, output_dir: str | Path | None = None) -> list[tuple[Concept, Path | None]]:
        """Run the full pipeline. Returns list of (Concept, video_path_or_None) pairs."""
        pdf_path = Path(pdf_path)
        if output_dir is None:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            output_dir = Path("output") / f"{pdf_path.stem}_{timestamp}"
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        console.print(Panel(
            f"[bold cyan]paper2vis[/] — [dim]{pdf_path.name}[/]\n"
            f"Extraction: [yellow]{self.provider}[/] / [dim]{self.model}[/]\n"
            f"Codegen:    [yellow]{self.codegen_provider}[/] / [dim]{self.codegen_model}[/]"
        ))

        # ── Stage 1: Parse ──────────────────────────────────────────────
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), TimeElapsedColumn(), console=console) as prog:
            task = prog.add_task("Parsing PDF…", total=None)
            paper = self.parser.parse(pdf_path)
            prog.update(task, description=f"[green]✓ Parsed[/] — {len(paper.sections)} sections")
            prog.stop()

        console.print(f"  [bold]Title:[/] {paper.title}")
        console.print(f"  [bold]Sections:[/] {len(paper.sections)}")
        if paper.abstract:
            console.print(f"  [bold]Abstract:[/] {paper.abstract[:200]}…")

        # ── Stage 1b: Figure extraction (optional) ───────────────────────
        extracted_figures: list[ExtractedFigure] = []
        if self.use_figure_context:
            with Progress(SpinnerColumn(), TextColumn("{task.description}"), TimeElapsedColumn(), console=console) as prog:
                task = prog.add_task("Extracting figures from PDF…", total=None)
                try:
                    extracted_figures = self.figure_extractor.extract(pdf_path)
                    prog.update(task, description=f"[green]✓ Figures[/] — {len(extracted_figures)} extracted")
                except Exception as exc:
                    prog.update(task, description="[yellow]⚠ Figure extraction failed[/]")
                    console.print(f"  [yellow]Warning:[/] figure extraction failed: {exc}")
                prog.stop()
            if extracted_figures:
                console.print(f"  [bold]Figures:[/] {len(extracted_figures)} extracted (largest first)")
                figs_dir = output_dir / "figures"
                figs_dir.mkdir(exist_ok=True)
                for idx, fig in enumerate(extracted_figures):
                    (figs_dir / f"figure_{idx:02d}_p{fig.page}.png").write_bytes(fig.image_bytes)
                console.print(f"  Saved → [dim]{figs_dir}[/]")

        # ── Stage 2: Extract concepts ────────────────────────────────────
        console.print("\n[bold yellow]Extracting concepts…[/]")
        all_concepts: list[Concept] = []
        seen_keys: list[str] = []

        with Progress(SpinnerColumn(), TextColumn("{task.description}"), TimeElapsedColumn(), console=console) as prog:
            task = prog.add_task("Calling LLM…", total=len(paper.sections))
            for section in paper.sections:
                prog.update(task, description=f"Section: {section.title[:50]}")
                try:
                    for c in self.extractor.extract(section.to_dict()):
                        key = normalize_concept_name(c.name)
                        if not any(names_overlap(key, existing) for existing in seen_keys):
                            seen_keys.append(key)
                            all_concepts.append(c)
                except Exception as exc:
                    console.print(f"  [red]Warning:[/] concept extraction failed for '{section.title}': {exc}")
                prog.advance(task)
                if len(all_concepts) >= self.max_concepts:
                    break

        all_concepts = all_concepts[: self.max_concepts]
        console.print(f"  [green]✓[/] Found [bold]{len(all_concepts)}[/] concepts")

        table = Table(title="Concepts", show_lines=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Name", style="bold")
        table.add_column("Visual Type", style="cyan")
        table.add_column("Description")
        for i, c in enumerate(all_concepts):
            table.add_row(str(i), c.name, c.visual_type, c.description)
        console.print(table)

        concepts_path = output_dir / "concepts.json"
        concepts_path.write_text(
            json.dumps([c.to_dict() for c in all_concepts], indent=2),
            encoding="utf-8",
        )
        console.print(f"  Saved → [dim]{concepts_path}[/]")

        # ── Stage 3 & 4: Code generation + rendering ─────────────────────
        manim_dir = output_dir / "manim"
        video_dir = output_dir / "videos"
        manim_dir.mkdir(parents=True, exist_ok=True)
        video_dir.mkdir(parents=True, exist_ok=True)

        results: list[tuple[Concept, Path | None]] = []

        for i, concept in enumerate(all_concepts):
            slug = _slugify(concept.name)
            console.print(f"\n[bold magenta][{i+1}/{len(all_concepts)}][/] {concept.name}")

            try:
                figure = extracted_figures[min(i, len(extracted_figures) - 1)] if extracted_figures else None
                storyboard = ""

                if figure:
                    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as prog:
                        prog.add_task("Generating code from figure…", total=None)
                        code = self.codegen.generate_from_figure(concept, figure.image_bytes)
                else:
                    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as prog:
                        prog.add_task("Planning storyboard…", total=None)
                        storyboard = self.codegen.get_storyboard(concept)
                    storyboard_path = manim_dir / f"concept_{i:02d}_{slug}.storyboard.md"
                    storyboard_path.write_text(storyboard, encoding="utf-8")
                    console.print(f"  [green]✓[/] Storyboard → [dim]{storyboard_path}[/]")

                    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as prog:
                        prog.add_task("Generating Manim code…", total=None)
                        code = self.codegen._code_from_storyboard(storyboard)

                code_path = manim_dir / f"concept_{i:02d}_{slug}.py"
                code_path.write_text(code, encoding="utf-8")
                console.print(f"  [green]✓[/] Code → [dim]{code_path}[/]")
            except Exception as exc:
                console.print(f"  [red]✗ Code generation failed:[/] {exc}")
                results.append((concept, None))
                continue

            if self.skip_render:
                console.print("  [dim]Skipping render (--skip-render)[/]")
                results.append((concept, None))
                continue

            video_path = self._render_with_retry(code, video_dir / slug, code_path)
            if video_path is not None:
                video_path = self._critic_pass(video_path, concept, storyboard, code, code_path, video_dir / slug)
            results.append((concept, video_path))

        n_rendered = sum(1 for _, v in results if v is not None)
        console.print(Panel(
            f"[bold green]Done![/]\n"
            f"Concepts: {len(all_concepts)} | Videos rendered: {n_rendered}\n"
            f"Output: [dim]{output_dir.resolve()}[/]"
        ))
        return results

    def _render_with_retry(
        self,
        code: str,
        output_dir: Path,
        code_path: Path,
        max_attempts: int = 3,
    ) -> Path | None:
        current_code = code
        seen_hashes: set[str] = {hashlib.md5(code.encode()).hexdigest()}
        for attempt in range(1, max_attempts + 1):
            try:
                with Progress(
                    SpinnerColumn(), TextColumn("{task.description}"), TimeElapsedColumn(), console=console
                ) as prog:
                    label = "Rendering with Manim…" if attempt == 1 else f"Rendering (attempt {attempt}/{max_attempts})…"
                    prog.add_task(label, total=None)
                    video_path = self.renderer.render(current_code, output_dir)
                console.print(f"  [green]✓[/] Video → [dim]{video_path}[/]")
                if attempt > 1:
                    code_path.write_text(current_code, encoding="utf-8")
                    console.print(f"  [green]✓[/] Fixed code saved → [dim]{code_path}[/]")
                return video_path
            except Exception as exc:
                console.print(f"  [yellow]⚠ Render attempt {attempt} failed[/]")
                if attempt < max_attempts:
                    console.print("  [dim]Asking LLM to fix the code…[/]")
                    try:
                        actionable = _actionable_error(str(exc))
                        fixed_code = self.codegen.fix_code(current_code, actionable)
                        new_hash = hashlib.md5(fixed_code.encode()).hexdigest()
                        if new_hash in seen_hashes:
                            console.print("  [yellow]⚠ LLM fix produced identical code — stopping retry[/]")
                            break
                        seen_hashes.add(new_hash)
                        current_code = fixed_code
                    except Exception as fix_exc:
                        console.print(f"  [red]✗ LLM fix failed:[/] {fix_exc}")
                        break
                else:
                    console.print(f"  [red]✗ Render failed after {max_attempts} attempts[/]")
        return None

    def _critic_pass(
        self,
        video_path: Path,
        concept: Concept,
        storyboard: str,
        code: str,
        code_path: Path,
        video_dir: Path,
    ) -> Path:
        """Run vision critic on a rendered video. If it fails, apply fix and re-render once."""
        console.print("  [dim]Running vision critique…[/]")
        try:
            result = self.critic.critique(
                video_path=video_path,
                concept_name=concept.name,
                concept_description=concept.description,
                storyboard=storyboard,
            )
        except Exception as exc:
            console.print(f"  [yellow]⚠ Critic failed (skipping):[/] {exc}")
            return video_path

        score_color = "green" if result.score >= 7 else "yellow" if result.score >= 5 else "red"
        status = "✓ passes" if result.passes else "✗ needs work"
        console.print(f"  Critic: [{score_color}]score {result.score}/10[/] {status}")

        # Save critique report alongside the code file
        critique_path = code_path.with_suffix(".critique.md")
        critique_path.write_text(_format_critique(result, concept.name, video_path), encoding="utf-8")
        console.print(f"  Critic report → [dim]{critique_path}[/]")

        if result.passes:
            return video_path

        for issue in result.issues:
            console.print(f"  [dim]  · {issue}[/]")
        console.print(f"  [dim]Fix: {result.fix_instruction[:120]}…[/]")

        try:
            with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as prog:
                prog.add_task("Applying critic fix…", total=None)
                fixed_code = self.codegen.apply_instruction(code, result.fix_instruction)

            with Progress(SpinnerColumn(), TextColumn("{task.description}"), TimeElapsedColumn(), console=console) as prog:
                prog.add_task("Re-rendering after critique…", total=None)
                new_video = self.renderer.render(fixed_code, video_dir)

            code_path.write_text(fixed_code, encoding="utf-8")
            console.print(f"  [green]✓[/] Critic-revised video → [dim]{new_video}[/]")
            return new_video
        except Exception as exc:
            console.print(f"  [yellow]⚠ Critic fix render failed, keeping original:[/] {exc}")
            return video_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

@app.command(name="run")
def main(
    pdf: Path = typer.Argument(..., help="Path to the input PDF", exists=True),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output directory"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p",
        help="Extraction LLM provider (anthropic|openai|ollama); defaults to LLM_PROVIDER env var"),
    model: Optional[str] = typer.Option(None, "--model", "-m",
        help="Extraction LLM model name; defaults to LLM_MODEL env var"),
    codegen_provider: Optional[str] = typer.Option(None, "--codegen-provider",
        help="Codegen LLM provider; defaults to CODEGEN_PROVIDER env var, then --provider"),
    codegen_model: Optional[str] = typer.Option(None, "--codegen-model",
        help="Codegen LLM model; defaults to CODEGEN_MODEL env var"),
    max_concepts: int = typer.Option(10, "--max-concepts", help="Maximum concepts to visualize"),
    quality: str = typer.Option("medium_quality", "--quality", "-q",
        help="Manim quality (low_quality|medium_quality|high_quality)"),
    skip_render: bool = typer.Option(False, "--skip-render", help="Generate code but skip Manim rendering"),
    figure_context: bool = typer.Option(False, "--figure-context/--no-figure-context",
        help="Extract and describe PDF figures to ground storyboard generation"),
) -> None:
    """Run the paper2vis pipeline on a PDF."""
    pipeline = Pipeline(
        provider=provider,
        model=model,
        codegen_provider=codegen_provider,
        codegen_model=codegen_model,
        max_concepts=max_concepts,
        render_quality=quality,
        skip_render=skip_render,
        use_figure_context=figure_context,
    )
    try:
        pipeline.run(pdf, output)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/]")
        sys.exit(1)
    except Exception as exc:
        console.print(f"[bold red]Fatal error:[/] {exc}")
        raise typer.Exit(1)


@app.command()
def fix(
    output_dir: Path = typer.Argument(..., help="Output directory from a previous pipeline run"),
    instruction: str = typer.Argument(..., help='Natural language correction, e.g. "make the arrows red"'),
    concept: Optional[str] = typer.Option(None, "--concept", "-c",
        help="Apply only to concepts whose name contains this string (case-insensitive)"),
    codegen_provider: Optional[str] = typer.Option(None, "--codegen-provider"),
    codegen_model: Optional[str] = typer.Option(None, "--codegen-model"),
    quality: str = typer.Option("medium_quality", "--quality", "-q",
        help="Manim quality (low_quality|medium_quality|high_quality)"),
    skip_render: bool = typer.Option(False, "--skip-render", help="Apply fix but skip re-rendering"),
) -> None:
    """Apply a natural-language correction to animations in an existing output directory."""
    output_dir = Path(output_dir)
    manim_dir = output_dir / "manim"
    video_dir = output_dir / "videos"

    if not manim_dir.exists():
        console.print(f"[red]No manim/ directory found in {output_dir}[/]")
        raise typer.Exit(1)

    py_files = sorted(manim_dir.glob("concept_*.py"))
    if not py_files:
        console.print(f"[red]No concept_*.py files found in {manim_dir}[/]")
        raise typer.Exit(1)

    if concept:
        py_files = [f for f in py_files if concept.lower() in f.stem.lower()]
        if not py_files:
            console.print(f"[yellow]No concept files match filter '{concept}'[/]")
            raise typer.Exit(0)

    codegen = ManimCodeGenerator(provider=codegen_provider, model=codegen_model)
    renderer = ManimRenderer(quality=quality)

    console.print(Panel(
        f"[bold cyan]paper2vis fix[/] — {len(py_files)} file(s)\n"
        f"[italic]{instruction}[/]"
    ))

    for py_file in py_files:
        console.print(f"\n[bold magenta]{py_file.name}[/]")
        code = py_file.read_text(encoding="utf-8")

        try:
            with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as prog:
                prog.add_task("Applying correction…", total=None)
                fixed_code = codegen.apply_instruction(code, instruction)
            py_file.write_text(fixed_code, encoding="utf-8")
            console.print(f"  [green]✓[/] Code updated → [dim]{py_file}[/]")
        except Exception as exc:
            console.print(f"  [red]✗ LLM correction failed:[/] {exc}")
            continue

        if skip_render:
            console.print("  [dim]Skipping render (--skip-render)[/]")
            continue

        slug = py_file.stem
        try:
            with Progress(SpinnerColumn(), TextColumn("{task.description}"), TimeElapsedColumn(), console=console) as prog:
                prog.add_task("Re-rendering…", total=None)
                video_path = renderer.render(fixed_code, video_dir / slug)
            console.print(f"  [green]✓[/] Video → [dim]{video_path}[/]")
        except Exception as exc:
            console.print(f"  [red]✗ Render failed:[/] {exc}")

    console.print(Panel(f"[bold green]Done![/] Fix applied to {len(py_files)} file(s)."))


def _format_critique(result, concept_name: str, video_path: Path) -> str:
    status = "PASS" if result.passes else "FAIL"
    score_bar = "█" * result.score + "░" * (10 - result.score)
    lines = [
        f"# Critic Report — {concept_name}",
        f"",
        f"**Score:** {result.score}/10  `{score_bar}`  **{status}**",
        f"",
        f"**Video:** `{video_path}`",
        f"",
    ]
    if result.issues:
        lines += ["## Issues", ""]
        for issue in result.issues:
            lines.append(f"- {issue}")
        lines.append("")
    if result.fix_instruction:
        lines += ["## Fix Applied", "", result.fix_instruction, ""]
    else:
        lines += ["## No fix needed", ""]
    return "\n".join(lines)


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40]


if __name__ == "__main__":
    app()
