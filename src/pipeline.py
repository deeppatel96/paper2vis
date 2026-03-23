"""
paper2vis main pipeline.

Orchestrates: PDF parse → concept extraction → Manim code generation → rendering.

Usage:
    python -m src.pipeline papers/mypaper.pdf [--output output/run] [--provider anthropic]
"""

from __future__ import annotations

import json
import os
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
from src.concepts.extractor import ConceptExtractor, Concept
from src.animation.codegen import ManimCodeGenerator
from src.animation.renderer import ManimRenderer

console = Console()
app = typer.Typer(help="paper2vis: turn academic papers into animations.")


# ---------------------------------------------------------------------------
# Pipeline class
# ---------------------------------------------------------------------------

class Pipeline:
    """End-to-end paper-to-visualization pipeline."""

    def __init__(
        self,
        provider: str = "anthropic",
        model: str | None = None,
        max_concepts: int = 10,
        render_quality: str = "medium_quality",
        skip_render: bool = False,
    ):
        self.provider = provider
        self.model = model or os.environ.get(
            "LLM_MODEL",
            "claude-opus-4-5" if provider == "anthropic" else "gpt-4o",
        )
        self.max_concepts = max_concepts
        self.render_quality = render_quality
        self.skip_render = skip_render

        self.parser = PDFParser()
        self.extractor = ConceptExtractor(provider=provider, model=self.model)
        self.codegen = ManimCodeGenerator(provider=provider, model=self.model)
        self.renderer = ManimRenderer(quality=render_quality)

    def run(self, pdf_path: str | Path, output_dir: str | Path | None = None) -> list[tuple[Concept, Path | None]]:
        """
        Run the full pipeline.

        Returns:
            List of (Concept, video_path_or_None) pairs.
        """
        pdf_path = Path(pdf_path)
        if output_dir is None:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            output_dir = Path("output") / f"{pdf_path.stem}_{timestamp}"
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        console.print(Panel(f"[bold cyan]paper2vis[/] — [dim]{pdf_path.name}[/]"))

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

        # ── Stage 2: Extract concepts ────────────────────────────────────
        console.print("\n[bold yellow]Extracting concepts…[/]")
        all_concepts: list[Concept] = []

        with Progress(SpinnerColumn(), TextColumn("{task.description}"), TimeElapsedColumn(), console=console) as prog:
            task = prog.add_task("Calling LLM…", total=len(paper.sections))
            for section in paper.sections:
                prog.update(task, description=f"Section: {section.title[:50]}")
                try:
                    concepts = self.extractor.extract(section.to_dict())
                    all_concepts.extend(concepts)
                except Exception as exc:
                    console.print(f"  [red]Warning:[/] concept extraction failed for '{section.title}': {exc}")
                prog.advance(task)
                if len(all_concepts) >= self.max_concepts:
                    break

        all_concepts = all_concepts[: self.max_concepts]
        console.print(f"  [green]✓[/] Found [bold]{len(all_concepts)}[/] concepts")

        # Pretty-print concept table
        table = Table(title="Concepts", show_lines=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Name", style="bold")
        table.add_column("Visual Type", style="cyan")
        table.add_column("Description")
        for i, c in enumerate(all_concepts):
            table.add_row(str(i), c.name, c.visual_type, c.description)
        console.print(table)

        # Save concepts JSON
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

            # Code generation
            try:
                with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as prog:
                    task = prog.add_task("Generating Manim code…", total=None)
                    code = self.codegen.generate(concept)

                code_path = manim_dir / f"concept_{i:02d}_{slug}.py"
                code_path.write_text(code, encoding="utf-8")
                console.print(f"  [green]✓[/] Code → [dim]{code_path}[/]")
            except Exception as exc:
                console.print(f"  [red]✗ Code generation failed:[/] {exc}")
                results.append((concept, None))
                continue

            # Rendering
            if self.skip_render:
                console.print("  [dim]Skipping render (--skip-render)[/]")
                results.append((concept, None))
                continue

            try:
                with Progress(SpinnerColumn(), TextColumn("{task.description}"), TimeElapsedColumn(), console=console) as prog:
                    task = prog.add_task("Rendering with Manim…", total=None)
                    video_path = self.renderer.render(code, video_dir / slug)
                console.print(f"  [green]✓[/] Video → [dim]{video_path}[/]")
                results.append((concept, video_path))
            except Exception as exc:
                console.print(f"  [red]✗ Render failed:[/] {exc}")
                results.append((concept, None))

        # ── Summary ──────────────────────────────────────────────────────
        n_rendered = sum(1 for _, v in results if v is not None)
        console.print(Panel(
            f"[bold green]Done![/]\n"
            f"Concepts: {len(all_concepts)} | Videos rendered: {n_rendered}\n"
            f"Output: [dim]{output_dir.resolve()}[/]"
        ))

        return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

@app.command()
def main(
    pdf: Path = typer.Argument(..., help="Path to the input PDF", exists=True),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output directory"),
    provider: str = typer.Option("anthropic", "--provider", "-p", help="LLM provider (anthropic|openai)"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="LLM model name"),
    max_concepts: int = typer.Option(10, "--max-concepts", help="Maximum concepts to visualize"),
    quality: str = typer.Option("medium_quality", "--quality", "-q", help="Manim quality (low_quality|medium_quality|high_quality)"),
    skip_render: bool = typer.Option(False, "--skip-render", help="Generate code but skip Manim rendering"),
) -> None:
    """Run the paper2vis pipeline on a PDF."""
    pipeline = Pipeline(
        provider=provider,
        model=model,
        max_concepts=max_concepts,
        render_quality=quality,
        skip_render=skip_render,
    )
    try:
        pipeline.run(pdf, output)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/]")
        sys.exit(1)
    except Exception as exc:
        console.print(f"[bold red]Fatal error:[/] {exc}")
        raise typer.Exit(1)


def _slugify(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40]


if __name__ == "__main__":
    app()
