"""
Typed animation DSL for paper2vis.

The LLM generates a JSON spec conforming to AnimationSpec.
DSLCompiler converts it to guaranteed-valid Manim code using only our layout helpers.

No arbitrary Python — every output line maps to a validated helper call or
a Manim API call we know works. Runtime errors become structurally impossible
for the set of operations the DSL expresses.
"""

from __future__ import annotations

import json
import re
import textwrap
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Valid colour names (subset of Manim palette that definitely exists)
# ---------------------------------------------------------------------------

_VALID_COLORS = {
    "BLUE", "BLUE_B", "BLUE_C", "BLUE_D",
    "GREEN", "GREEN_B", "GREEN_C",
    "RED", "ORANGE", "YELLOW",
    "WHITE", "BLACK",
    "GREY", "GREY_A", "GREY_B", "GREY_C", "GREY_D",
    "TEAL", "TEAL_A", "TEAL_B",
    "PURPLE", "PURPLE_A", "PURPLE_B",
    "PINK", "GOLD", "GOLD_A", "GOLD_B", "MAROON",
}

_POSITION_Y = {"upper": "+ UP*1.5", "center": "", "lower": "+ DOWN*1.2"}


def _safe_color(c: str, default: str = "BLUE") -> str:
    c = c.upper().replace(" ", "_")
    return c if c in _VALID_COLORS else default


def _color_list(colors: Optional[List[str]], n: int, default: str = "BLUE") -> List[str]:
    if not colors:
        return [default] * n
    result = [_safe_color(c, default) for c in colors]
    # pad / trim to length n
    while len(result) < n:
        result.append(result[-1] if result else default)
    return result[:n]


def _safe_str(s: str) -> str:
    """Escape a string for use inside Text("...") double-quote context."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


# ---------------------------------------------------------------------------
# Beat models
# ---------------------------------------------------------------------------

class NodeRowBeat(BaseModel):
    type: Literal["node_row"]
    labels: List[str] = Field(min_length=1, max_length=12)
    colors: Optional[List[str]] = None
    weights: Optional[List[float]] = None
    subtitle: Optional[str] = None
    position: Literal["upper", "center", "lower"] = "upper"


class HeatmapBeat(BaseModel):
    type: Literal["heatmap"]
    matrix: List[List[float]] = Field(min_length=1, max_length=10)
    row_labels: Optional[List[str]] = None
    col_labels: Optional[List[str]] = None
    title: Optional[str] = None
    highlight_row: Optional[int] = None

    @field_validator("matrix")
    @classmethod
    def clamp_values(cls, m: List[List[float]]) -> List[List[float]]:
        return [[max(0.0, min(1.0, v)) for v in row] for row in m]


class BarChartBeat(BaseModel):
    type: Literal["bar_chart"]
    values: List[float] = Field(min_length=1, max_length=8)
    labels: List[str]
    colors: Optional[List[str]] = None
    title: Optional[str] = None
    then_transform: Optional[List[float]] = None  # animate rescaling to these values

    @model_validator(mode="after")
    def align_lengths(self) -> "BarChartBeat":
        n = len(self.values)
        if len(self.labels) != n:
            self.labels = (self.labels + self.labels)[:n]
        if self.then_transform and len(self.then_transform) != n:
            self.then_transform = (self.then_transform + [0.0] * n)[:n]
        return self


class SideBySideBeat(BaseModel):
    type: Literal["side_by_side"]
    labels: List[str] = Field(min_length=1, max_length=5)
    colors: Optional[List[str]] = None
    highlight: Optional[int] = None


class FlowColumnBeat(BaseModel):
    type: Literal["flow_column"]
    labels: List[str] = Field(min_length=1, max_length=8)
    colors: Optional[List[str]] = None
    highlight: Optional[int] = None


class TextBeat(BaseModel):
    type: Literal["text"]
    content: str
    subtitle: Optional[str] = None
    color: Optional[str] = "WHITE"


class WeightedConnectionsBeat(BaseModel):
    """Two node rows with weighted lines between them — ideal for attention."""
    type: Literal["weighted_connections"]
    from_labels: List[str] = Field(min_length=1, max_length=8)
    to_labels: List[str] = Field(min_length=1, max_length=8)
    weights: List[List[float]]  # len(from_labels) × len(to_labels)
    from_colors: Optional[List[str]] = None
    to_colors: Optional[List[str]] = None
    title: Optional[str] = None

    @field_validator("weights")
    @classmethod
    def clamp_weights(cls, w: List[List[float]]) -> List[List[float]]:
        return [[max(0.0, min(1.0, v)) for v in row] for row in w]


Beat = Annotated[
    Union[
        NodeRowBeat, HeatmapBeat, BarChartBeat,
        SideBySideBeat, FlowColumnBeat, TextBeat,
        WeightedConnectionsBeat,
    ],
    Field(discriminator="type"),
]


class AnimationSpec(BaseModel):
    title: str
    class_name: str = "GeneratedScene"
    beats: List[Beat] = Field(min_length=1, max_length=8)

    @field_validator("class_name")
    @classmethod
    def valid_class_name(cls, v: str) -> str:
        v = re.sub(r"[^A-Za-z0-9]", "", v)
        return v if v else "GeneratedScene"


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------

class DSLCompiler:
    """
    Compiles an AnimationSpec into a complete, runnable Manim scene.

    Every emitted line uses either:
      - Our auto-injected layout helpers (node_row, heatmap, bar_chart, …)
      - A verified Manim animation call (FadeIn, Create, LaggedStart, …)
    No arbitrary Python that could produce undefined-name or type errors.
    """

    def compile(self, spec: AnimationSpec) -> str:
        header = textwrap.dedent(f"""\
            from manim import *
            import numpy as np

            class {spec.class_name}(Scene):
                def construct(self):
                    title = Text("{_safe_str(spec.title)}", font_size=34).to_edge(UP)
                    self.play(FadeIn(title))
                    self.wait(0.5)
        """)

        body_lines: List[str] = []
        for i, beat in enumerate(spec.beats):
            beat_code, group_var = self._compile_beat(beat, i)
            body_lines.extend(beat_code)
            # Fade out between beats (not after last)
            if i < len(spec.beats) - 1:
                body_lines.append(f"        self.play(FadeOut({group_var}))")
                body_lines.append("")

        return header + "\n".join(body_lines) + "\n"

    # ------------------------------------------------------------------

    def _indent(self, lines: List[str]) -> List[str]:
        return ["        " + ln for ln in lines]

    def _compile_beat(self, beat: Beat, idx: int) -> tuple[List[str], str]:
        """Returns (indented_lines, group_var_name)."""
        lines: List[str] = []
        v = f"_g{idx}"  # group variable for this beat

        if isinstance(beat, NodeRowBeat):
            n = len(beat.labels)
            colors = _color_list(beat.colors, n)
            pos_suffix = _POSITION_Y.get(beat.position, "")
            pos = f"CONTENT_CENTER {pos_suffix}".strip()
            labels_r = repr(beat.labels)
            colors_r = repr(colors)
            lines += [
                f"# Beat {idx+1}: node row",
                f"_c{idx}, _t{idx} = node_row({labels_r}, {colors_r}, center={pos})",
                f"self.play(LaggedStart(*[Create(c) for c in _c{idx}], lag_ratio=0.15))",
                f"self.play(LaggedStart(*[FadeIn(t) for t in _t{idx}], lag_ratio=0.15))",
            ]
            if beat.weights and len(beat.weights) == n:
                wvars = []
                for j, w in enumerate(beat.weights):
                    wv = f"_wt{idx}_{j}"
                    lines.append(
                        f'{wv} = Text("{w:.2f}", font_size=14, color=GREY_B)'
                        f".next_to(_c{idx}[{j}], DOWN, buff=0.14)"
                    )
                    wvars.append(wv)
                lines.append(
                    f"self.play(LaggedStart(*[FadeIn(w) for w in [{', '.join(wvars)}]], lag_ratio=0.1))"
                )
            sub_var = ""
            if beat.subtitle:
                sub_var = f"_sub{idx}"
                lines += [
                    f'{sub_var} = Text("{_safe_str(beat.subtitle)}", font_size=17, color=GREY_B)'
                    f".next_to(_c{idx}, DOWN, buff=0.55)",
                    f"self.play(FadeIn({sub_var}))",
                ]
            lines.append("self.wait(2.0)")
            group_parts = f"_c{idx}, _t{idx}" + (f", {sub_var}" if sub_var else "")
            lines.append(f"{v} = VGroup({group_parts})")

        elif isinstance(beat, HeatmapBeat):
            rl = repr(beat.row_labels)
            cl = repr(beat.col_labels)
            mat_r = repr(beat.matrix)
            lines += [f"# Beat {idx+1}: heatmap"]
            title_var = ""
            if beat.title:
                title_var = f"_ht{idx}"
                lines += [
                    f'{title_var} = Text("{_safe_str(beat.title)}", font_size=20)'
                    f".move_to(CONTENT_CENTER + UP*1.85)",
                    f"self.play(FadeIn({title_var}))",
                ]
            lines += [
                f"_heat{idx} = heatmap({mat_r}, row_labels={rl}, col_labels={cl},"
                f" center=CONTENT_CENTER + DOWN*0.3)",
                f"self.play(FadeIn(_heat{idx}), run_time=0.9)",
            ]
            if beat.highlight_row is not None:
                n_rows = len(beat.matrix)
                n_cols = len(beat.matrix[0]) if beat.matrix else 1
                row_y = f"(({n_rows - 1}/2.0 - {beat.highlight_row}) * 0.62)"
                lines += [
                    f"_hrow{idx} = Rectangle(width={n_cols}*0.62+0.1, height=0.56,"
                    f" color=YELLOW, stroke_width=2, fill_opacity=0)",
                    f"_hrow{idx}.move_to(CONTENT_CENTER + DOWN*0.3 + UP*{row_y})",
                    f"self.play(Create(_hrow{idx}))",
                ]
            lines.append("self.wait(2.5)")
            group_parts = f"_heat{idx}" + (f", {title_var}" if title_var else "")
            lines.append(f"{v} = VGroup({group_parts})")

        elif isinstance(beat, BarChartBeat):
            n = len(beat.values)
            colors = _color_list(beat.colors, n, "ORANGE")
            values_r = repr(beat.values)
            labels_r = repr(beat.labels[:n])
            colors_r = repr(colors)
            lines += [f"# Beat {idx+1}: bar chart"]
            title_var = ""
            if beat.title:
                title_var = f"_bt{idx}"
                lines += [
                    f'{title_var} = Text("{_safe_str(beat.title)}", font_size=20)'
                    f".move_to(CONTENT_CENTER + UP*1.85)",
                    f"self.play(FadeIn({title_var}))",
                ]
            lines += [
                f"_bars{idx}, _blbls{idx}, _bbase{idx} = bar_chart("
                f"{values_r}, {labels_r}, colors={colors_r}, center=CONTENT_CENTER)",
                f"self.play(Create(_bbase{idx}))",
                f"animate_bars(self, _bars{idx}, _bbase{idx})",
                f"self.play(LaggedStart(*[FadeIn(l) for l in _blbls{idx}], lag_ratio=0.1))",
            ]
            if beat.then_transform:
                old_v = beat.values
                new_v = beat.then_transform
                lines.append("self.wait(1.5)")
                transform_parts = []
                for j, (ov, nv) in enumerate(zip(old_v, new_v)):
                    sf = max(nv, 0.001) / max(ov, 0.001)
                    transform_parts.append(
                        f"Transform(_bars{idx}[{j}], _bars{idx}[{j}].copy()"
                        f".stretch({sf:.4f}, 1, about_edge=DOWN))"
                    )
                lines.append(f"self.play({', '.join(transform_parts)})")
            lines.append("self.wait(2.0)")
            group_parts = f"VGroup(*_bars{idx}, *_blbls{idx}, _bbase{idx})"
            if title_var:
                group_parts = f"VGroup({title_var}, {group_parts})"
            lines.append(f"{v} = {group_parts}")

        elif isinstance(beat, SideBySideBeat):
            n = len(beat.labels)
            colors = _color_list(beat.colors, n, "BLUE")
            labels_r = repr(beat.labels)
            colors_r = repr(colors)
            lines += [
                f"# Beat {idx+1}: side by side",
                f"_boxes{idx}, _arrs{idx} = side_by_side({labels_r}, stage_colors={colors_r},"
                f" center=CONTENT_CENTER)",
                f"self.play(LaggedStart(*[FadeIn(b) for b in _boxes{idx}], lag_ratio=0.3))",
                f"self.play(LaggedStart(*[Create(a) for a in _arrs{idx}], lag_ratio=0.3))",
            ]
            if beat.highlight is not None and 0 <= beat.highlight < n:
                lines.append(f"self.play(Indicate(_boxes{idx}[{beat.highlight}], scale_factor=1.08))")
            lines.append("self.wait(2.0)")
            lines.append(f"{v} = VGroup(*_boxes{idx}, *_arrs{idx})")

        elif isinstance(beat, FlowColumnBeat):
            n = len(beat.labels)
            colors = _color_list(beat.colors, n, "TEAL")
            labels_r = repr(beat.labels)
            colors_r = repr(colors)
            lines += [
                f"# Beat {idx+1}: flow column",
                f"_fboxes{idx}, _farrs{idx} = flow_column({labels_r}, stage_colors={colors_r},"
                f" center=CONTENT_CENTER)",
                f"self.play(LaggedStart(*[FadeIn(b) for b in _fboxes{idx}], lag_ratio=0.3))",
                f"self.play(LaggedStart(*[Create(a) for a in _farrs{idx}], lag_ratio=0.3))",
            ]
            if beat.highlight is not None and 0 <= beat.highlight < n:
                lines.append(f"self.play(Indicate(_fboxes{idx}[{beat.highlight}], scale_factor=1.08))")
            lines.append("self.wait(2.0)")
            lines.append(f"{v} = VGroup(*_fboxes{idx}, *_farrs{idx})")

        elif isinstance(beat, TextBeat):
            color = _safe_color(beat.color or "WHITE", "WHITE")
            lines += [
                f"# Beat {idx+1}: text",
                f'_txt{idx} = Text("{_safe_str(beat.content)}", font_size=28, color={color})'
                f".move_to(CONTENT_CENTER + UP*0.4)",
                f"self.play(Write(_txt{idx}))",
            ]
            sub_var = ""
            if beat.subtitle:
                sub_var = f"_sub{idx}"
                lines += [
                    f'{sub_var} = Text("{_safe_str(beat.subtitle)}", font_size=18, color=GREY_B)'
                    f".next_to(_txt{idx}, DOWN, buff=0.3)",
                    f"self.play(FadeIn({sub_var}))",
                ]
            lines.append("self.wait(2.0)")
            group_parts = f"_txt{idx}" + (f", {sub_var}" if sub_var else "")
            lines.append(f"{v} = VGroup({group_parts})")

        elif isinstance(beat, WeightedConnectionsBeat):
            n_from = len(beat.from_labels)
            n_to = len(beat.to_labels)
            fc = _color_list(beat.from_colors, n_from, "BLUE_C")
            tc = _color_list(beat.to_colors, n_to, "GREEN_C")
            fl_r = repr(beat.from_labels)
            tl_r = repr(beat.to_labels)
            fc_r = repr(fc)
            tc_r = repr(tc)
            w_r = repr(beat.weights)
            lines += [
                f"# Beat {idx+1}: weighted connections",
            ]
            if beat.title:
                lines += [
                    f'_wt{idx} = Text("{_safe_str(beat.title)}", font_size=20)'
                    f".move_to(CONTENT_CENTER + UP*2.1)",
                    f"self.play(FadeIn(_wt{idx}))",
                ]
            lines += [
                f"_fc{idx}, _ft{idx} = node_row({fl_r}, {fc_r}, center=CONTENT_CENTER + UP*1.5, spacing=1.4)",
                f"_tc{idx}, _tt{idx} = node_row({tl_r}, {tc_r}, center=CONTENT_CENTER + DOWN*0.5, spacing=1.4)",
                f"self.play(LaggedStart(*[Create(c) for c in _fc{idx}], lag_ratio=0.12))",
                f"self.play(LaggedStart(*[FadeIn(t) for t in _ft{idx}], lag_ratio=0.12))",
                f"self.play(LaggedStart(*[Create(c) for c in _tc{idx}], lag_ratio=0.12))",
                f"self.play(LaggedStart(*[FadeIn(t) for t in _tt{idx}], lag_ratio=0.12))",
                f"_wmat{idx} = {w_r}",
                f"_wlines{idx} = VGroup()",
                f"for _i in range(len(_fc{idx})):",
                f"    for _j in range(len(_tc{idx})):",
                f"        _w = float(_wmat{idx}[_i][_j])",
                f"        _col = interpolate_color(GREY_C, YELLOW, min(1.0, _w * 2.5))",
                f"        _wlines{idx}.add(Line(_fc{idx}[_i].get_bottom(), _tc{idx}[_j].get_top(),"
                f" stroke_width=max(0.5, _w * 12), color=_col, stroke_opacity=0.75))",
                f"self.play(LaggedStart(*[Create(l) for l in _wlines{idx}], lag_ratio=0.04))",
                f"self.wait(2.5)",
                f"{v} = VGroup(_fc{idx}, _ft{idx}, _tc{idx}, _tt{idx}, _wlines{idx})",
            ]
            if beat.title:
                lines[-1] = f"{v} = VGroup(_fc{idx}, _ft{idx}, _tc{idx}, _tt{idx}, _wlines{idx}, _wt{idx})"

        return self._indent(lines), v


# ---------------------------------------------------------------------------
# Parse + validate JSON from LLM response
# ---------------------------------------------------------------------------

def parse_spec(raw: str) -> AnimationSpec:
    """Extract and validate AnimationSpec JSON from an LLM response string."""
    # Try fenced JSON block first
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if not m:
        m = re.search(r"(\{.*\})", raw, re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in LLM response")
    return AnimationSpec.model_validate_json(m.group(1))
