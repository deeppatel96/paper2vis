"""
Reusable Manim scene base classes for paper2vis.

Generated scenes can inherit from these to get common behaviour for free,
or they can be used directly as standalone scenes.
"""

from __future__ import annotations

from manim import (
    DOWN,
    LEFT,
    RIGHT,
    UP,
    Arrow,
    Create,
    FadeIn,
    FadeOut,
    MathTex,
    Mobject,
    ReplacementTransform,
    Scene,
    Text,
    TransformMatchingTex,
    VGroup,
    Write,
    Rectangle,
    RoundedRectangle,
    WHITE,
    BLUE,
    GREEN,
    YELLOW,
    ORANGE,
    ThreeDScene,
)
from typing import Sequence


# ---------------------------------------------------------------------------
# EquationTransformScene
# ---------------------------------------------------------------------------

class EquationTransformScene(Scene):
    """
    Animates a sequence of equation transformations, step by step.

    Usage::

        class MyScene(EquationTransformScene):
            equations = [
                r"E = mc^2",
                r"E / c^2 = m",
                r"m = \frac{E}{c^2}",
            ]
            title = "Rearranging Einstein's relation"
    """

    equations: Sequence[str] = []
    title: str = ""
    pause_between: float = 1.5

    def construct(self) -> None:
        if not self.equations:
            raise ValueError("Set the `equations` class attribute with a list of LaTeX strings.")

        # Optional title
        if self.title:
            title_mob = Text(self.title, font_size=36).to_edge(UP)
            self.play(FadeIn(title_mob))
            self.wait(0.5)

        # Show the first equation
        current = MathTex(self.equations[0])
        self.play(Write(current))
        self.wait(self.pause_between)

        # Transform through each subsequent equation
        for eq_str in self.equations[1:]:
            next_eq = MathTex(eq_str)
            self.play(TransformMatchingTex(current, next_eq))
            self.wait(self.pause_between)
            current = next_eq

        self.wait(1)


# ---------------------------------------------------------------------------
# ConceptDiagramScene
# ---------------------------------------------------------------------------

class ConceptDiagramScene(Scene):
    """
    Base class for concept diagram animations.

    Subclasses override `build_diagram()` to add Mobjects and animations.
    Provides helpers for labelled boxes and connecting arrows.
    """

    title: str = ""
    background_color: str = "#1e1e2e"

    def construct(self) -> None:
        if self.title:
            title_mob = Text(self.title, font_size=40).to_edge(UP)
            self.play(FadeIn(title_mob))
            self.wait(0.3)

        self.build_diagram()

    def build_diagram(self) -> None:
        """Override this in subclasses to add your diagram elements."""
        placeholder = Text("Override build_diagram() in your subclass.", font_size=24)
        self.play(FadeIn(placeholder))
        self.wait(2)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def make_box(
        self,
        label: str,
        width: float = 2.5,
        height: float = 0.8,
        color: str = BLUE,
        font_size: int = 24,
    ) -> VGroup:
        """Create a labelled rounded rectangle."""
        rect = RoundedRectangle(
            width=width, height=height, corner_radius=0.1, color=color
        )
        text = Text(label, font_size=font_size).move_to(rect.get_center())
        return VGroup(rect, text)

    def connect(
        self,
        start_mob: Mobject,
        end_mob: Mobject,
        label: str = "",
        color: str = WHITE,
    ) -> VGroup:
        """Draw an arrow between two Mobjects, optionally with a label."""
        arrow = Arrow(
            start=start_mob.get_right(),
            end=end_mob.get_left(),
            color=color,
            buff=0.1,
        )
        group: list[Mobject] = [arrow]
        if label:
            lbl = Text(label, font_size=18).next_to(arrow, UP, buff=0.1)
            group.append(lbl)
        return VGroup(*group)


# ---------------------------------------------------------------------------
# FlowScene
# ---------------------------------------------------------------------------

class FlowScene(ConceptDiagramScene):
    """
    Animated flowchart / pipeline diagram.

    Define the pipeline stages and connections:

    Usage::

        class MyPipeline(FlowScene):
            title = "Transformer Forward Pass"
            stages = [
                "Input Embedding",
                "Multi-Head Attention",
                "Add & Norm",
                "Feed Forward",
                "Output",
            ]
    """

    stages: Sequence[str] = []
    stage_color: str = BLUE
    arrow_color: str = WHITE
    box_width: float = 3.0
    box_height: float = 0.7
    vertical_spacing: float = 1.2

    def build_diagram(self) -> None:
        if not self.stages:
            self.play(FadeIn(Text("Set `stages` on your FlowScene subclass.", font_size=24)))
            self.wait(2)
            return

        boxes: list[VGroup] = []
        n = len(self.stages)
        # Center the whole stack vertically
        start_y = (n - 1) / 2 * self.vertical_spacing

        for i, stage_name in enumerate(self.stages):
            box = self.make_box(
                stage_name,
                width=self.box_width,
                height=self.box_height,
                color=self.stage_color,
            )
            box.move_to([0, start_y - i * self.vertical_spacing, 0])
            boxes.append(box)

        # Animate boxes appearing one by one
        for box in boxes:
            self.play(FadeIn(box), run_time=0.5)

        self.wait(0.5)

        # Animate arrows between boxes
        arrows: list[Arrow] = []
        for i in range(len(boxes) - 1):
            arrow = Arrow(
                start=boxes[i].get_bottom(),
                end=boxes[i + 1].get_top(),
                color=self.arrow_color,
                buff=0.05,
            )
            arrows.append(arrow)
            self.play(Create(arrow), run_time=0.4)

        self.wait(1.5)

        # Optional: highlight each stage in sequence
        for box in boxes:
            rect = box[0]  # The RoundedRectangle
            original_color = rect.get_color()
            rect.set_color(YELLOW)
            self.wait(0.3)
            rect.set_color(original_color)

        self.wait(1)
