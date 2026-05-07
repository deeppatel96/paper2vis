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


class AttentionMatrixBeat(BaseModel):
    """Attention score matrix heatmap with optional query-row highlight."""
    type: Literal["attention_matrix"]
    query_labels: List[str] = Field(min_length=1, max_length=8)
    key_labels: List[str] = Field(min_length=1, max_length=8)
    scores: List[List[float]]  # n_queries × n_keys, values in [0,1]
    highlight_query: Optional[int] = None  # index of query row to highlight
    title: Optional[str] = None

    @field_validator("scores")
    @classmethod
    def clamp_scores(cls, s: List[List[float]]) -> List[List[float]]:
        return [[max(0.0, min(1.0, v)) for v in row] for row in s]


class BayesDiagramBeat(BaseModel):
    """Animate a Bayesian update: prior bar chart transforms into posterior."""
    type: Literal["bayes"]
    hypotheses: List[str] = Field(min_length=2, max_length=6)
    prior: List[float]       # unnormalized; will be normalised automatically
    likelihood: List[float]  # P(evidence | hypothesis) for each hypothesis
    title: Optional[str] = None

    @model_validator(mode="after")
    def align_and_normalize(self) -> "BayesDiagramBeat":
        n = len(self.hypotheses)
        self.prior = (list(self.prior) + [1.0 / n] * n)[:n]
        self.likelihood = (list(self.likelihood) + [0.5] * n)[:n]
        total = sum(self.prior)
        if total > 0:
            self.prior = [p / total for p in self.prior]
        return self


class GradientStepBeat(BaseModel):
    """Loss curve with an animated gradient-descent dot trajectory."""
    type: Literal["gradient_step"]
    fn_type: Literal["quadratic", "cubic", "sine"] = "quadratic"
    a: float = 1.0   # leading coefficient
    b: float = 0.0   # quadratic: ax²+bx+c; cubic: ax³+bx²+cx+d; sine: a·sin(b·x)+c
    c: float = 0.0
    d: float = 0.0   # cubic only: constant term
    x_range: List[float] = [-3.0, 3.0]
    start_x: float = 2.5
    learning_rate: float = 0.3
    n_steps: int = Field(default=5, ge=1, le=8)
    title: Optional[str] = None

    @field_validator("x_range")
    @classmethod
    def valid_range(cls, v: List[float]) -> List[float]:
        if len(v) < 2 or v[0] >= v[1]:
            return [-3.0, 3.0]
        return v[:2]


class EigendecompositionBeat(BaseModel):
    """2×2 (or 3×3) matrix with eigenvector arrows on a coordinate plane."""
    type: Literal["eigendecomposition"]
    matrix: List[List[float]]
    eigenvalues: List[float]
    eigenvectors: List[List[float]]  # each sub-list is one eigenvector (2- or 3-D)
    labels: Optional[List[str]] = None  # e.g. ["λ₁", "λ₂"]
    title: Optional[str] = None

    @field_validator("matrix")
    @classmethod
    def validate_square(cls, m: List[List[float]]) -> List[List[float]]:
        n = len(m)
        if n < 2 or n > 3:
            raise ValueError("Only 2×2 and 3×3 matrices supported")
        if not all(len(row) == n for row in m):
            raise ValueError("Matrix must be square")
        return m


class TreeBeat(BaseModel):
    """Tree (or DAG) with optional BFS/DFS traversal highlight animation."""
    type: Literal["tree"]
    nodes: List[str] = Field(min_length=2, max_length=15)
    edges: List[List[int]]           # [[parent_idx, child_idx], ...]
    traversal_order: Optional[List[int]] = None  # node indices to highlight in order
    title: Optional[str] = None
    node_color: Optional[str] = "BLUE"
    highlight_color: Optional[str] = "YELLOW"


Beat = Annotated[
    Union[
        NodeRowBeat, HeatmapBeat, BarChartBeat,
        SideBySideBeat, FlowColumnBeat, TextBeat,
        WeightedConnectionsBeat,
        AttentionMatrixBeat, BayesDiagramBeat,
        GradientStepBeat, EigendecompositionBeat,
        TreeBeat,
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

        elif isinstance(beat, AttentionMatrixBeat):
            n_q = len(beat.query_labels)
            n_k = len(beat.key_labels)
            ql_r = repr(beat.query_labels)
            kl_r = repr(beat.key_labels)
            sc_r = repr(beat.scores)
            lines = [f"# Beat {idx+1}: attention matrix"]
            title_var = ""
            if beat.title:
                title_var = f"_at{idx}"
                lines += [
                    f'{title_var} = Text("{_safe_str(beat.title)}", font_size=20)'
                    f".move_to(CONTENT_CENTER + UP*1.85)",
                    f"self.play(FadeIn({title_var}))",
                ]
            lines += [
                f"_heat{idx} = heatmap({sc_r}, row_labels={ql_r}, col_labels={kl_r},"
                f" center=CONTENT_CENTER + DOWN*0.2)",
                f"self.play(FadeIn(_heat{idx}), run_time=0.9)",
            ]
            if beat.highlight_query is not None and 0 <= beat.highlight_query < n_q:
                row_y = round((n_q - 1) / 2.0 - beat.highlight_query, 4) * 0.62
                lines += [
                    f"_hrow{idx} = Rectangle(width={n_k}*0.62+0.1, height=0.56,"
                    f" color=YELLOW, stroke_width=2.5, fill_opacity=0.12, fill_color=YELLOW)",
                    f"_hrow{idx}.move_to(CONTENT_CENTER + DOWN*0.2 + UP*{row_y:.4f})",
                    f"self.play(Create(_hrow{idx}))",
                ]
            lines.append("self.wait(2.5)")
            group_parts = [f"_heat{idx}"]
            if beat.highlight_query is not None:
                group_parts.append(f"_hrow{idx}")
            if title_var:
                group_parts.insert(0, title_var)
            lines.append(f"{v} = VGroup({', '.join(group_parts)})")

        elif isinstance(beat, BayesDiagramBeat):
            prior = list(beat.prior)
            likelihood = list(beat.likelihood)
            unnorm = [p * l for p, l in zip(prior, likelihood)]
            total = sum(unnorm) or 1e-9
            posterior = [u / total for u in unnorm]

            n = len(beat.hypotheses)
            hyp_r = repr(beat.hypotheses)
            prior_r = repr([round(p, 4) for p in prior])
            pc_r = repr(["BLUE_C"] * n)
            transform_parts = []
            for j, (pv, postv) in enumerate(zip(prior, posterior)):
                sf = round(max(postv, 0.001) / max(pv, 0.001), 4)
                transform_parts.append(
                    f"_bars{idx}[{j}].animate.stretch({sf}, 1, about_edge=DOWN).set_color(GREEN_C)"
                )
            lines = [f"# Beat {idx+1}: Bayes update"]
            title_var = ""
            if beat.title:
                title_var = f"_byt{idx}"
                lines += [
                    f'{title_var} = Text("{_safe_str(beat.title)}", font_size=20)'
                    f".move_to(CONTENT_CENTER + UP*1.85)",
                    f"self.play(FadeIn({title_var}))",
                ]
            lines += [
                f"_bars{idx}, _blbls{idx}, _bbase{idx} = bar_chart({prior_r}, {hyp_r},"
                f" colors={pc_r}, center=CONTENT_CENTER + DOWN*0.3)",
                f"self.play(Create(_bbase{idx}))",
                f"animate_bars(self, _bars{idx}, _bbase{idx})",
                f"self.play(LaggedStart(*[FadeIn(l) for l in _blbls{idx}], lag_ratio=0.1))",
                f"self.wait(1.2)",
                f'_bform{idx} = Text("Posterior ∝ Likelihood × Prior", font_size=15, color=GREY_B)'
                f".move_to(CONTENT_CENTER + UP*1.5)",
                f"self.play(FadeIn(_bform{idx}))",
                f"self.wait(0.8)",
                f"self.play({', '.join(transform_parts)}, run_time=1.5)",
                f"self.wait(2.0)",
            ]
            group_parts = [f"VGroup(*_bars{idx}, *_blbls{idx}, _bbase{idx}, _bform{idx})"]
            if title_var:
                group_parts.insert(0, title_var)
            lines.append(f"{v} = VGroup({', '.join(group_parts)})")

        elif isinstance(beat, GradientStepBeat):
            import math as _math
            a, b, c, d = beat.a, beat.b, beat.c, beat.d
            ft = beat.fn_type
            x1, x2 = beat.x_range[0], beat.x_range[1]
            lr = beat.learning_rate

            if ft == "quadratic":
                fn = lambda x, _a=a, _b=b, _c=c: _a*x**2 + _b*x + _c
                dfn = lambda x, _a=a, _b=b: 2*_a*x + _b
                fn_str = f"lambda x: {a}*x**2 + {b}*x + {c}"
            elif ft == "cubic":
                fn = lambda x, _a=a, _b=b, _c=c, _d=d: _a*x**3 + _b*x**2 + _c*x + _d
                dfn = lambda x, _a=a, _b=b, _c=c: 3*_a*x**2 + 2*_b*x + _c
                fn_str = f"lambda x: {a}*x**3 + {b}*x**2 + {c}*x + {d}"
            else:  # sine
                fn = lambda x, _a=a, _b=b, _c=c: _a*_math.sin(_b*x) + _c
                dfn = lambda x, _a=a, _b=b: _a*_b*_math.cos(_b*x)
                fn_str = f"lambda x: {a}*np.sin({b}*x) + {c}"

            # Pre-compute trajectory in Python (safe, no Manim involved)
            cur_x = max(x1 + 0.1, min(x2 - 0.1, beat.start_x))
            trajectory = [(cur_x, fn(cur_x))]
            for _ in range(beat.n_steps):
                grad = dfn(cur_x)
                cur_x = max(x1 + 0.05, min(x2 - 0.05, cur_x - lr * float(grad)))
                trajectory.append((cur_x, float(fn(cur_x))))

            xs = [x1 + (x2 - x1) * i / 59 for i in range(60)]
            ys = [float(fn(x)) for x in xs] + [pt[1] for pt in trajectory]
            y1 = round(min(ys) - 0.8, 1)
            y2 = round(max(ys) + 0.8, 1)
            x_step = round((x2 - x1) / 6, 1) or 0.5
            y_step = max(0.5, round((y2 - y1) / 5, 1))
            traj_r = repr([(round(x, 4), round(y, 4)) for x, y in trajectory])

            lines = [f"# Beat {idx+1}: gradient descent ({ft})"]
            title_var = ""
            if beat.title:
                title_var = f"_gdt{idx}"
                lines += [
                    f'{title_var} = Text("{_safe_str(beat.title)}", font_size=20)'
                    f".move_to(CONTENT_CENTER + UP*1.85)",
                    f"self.play(FadeIn({title_var}))",
                ]
            lines += [
                f'_axes{idx} = Axes(x_range=[{x1}, {x2}, {x_step}], y_range=[{y1}, {y2}, {y_step}], x_length=6.0, y_length=3.5, axis_config={{"color": GREY_B, "tip_length": 0.15}})',
                f"_axes{idx}.move_to(CONTENT_CENTER + DOWN*0.3)",
                f"_curve{idx} = _axes{idx}.plot({fn_str}, color=BLUE_C, stroke_width=2.5)",
                f"self.play(Create(_axes{idx}), Create(_curve{idx}), run_time=1.0)",
                f"_traj{idx} = {traj_r}",
                f"_dot{idx} = Dot(_axes{idx}.c2p(_traj{idx}[0][0], _traj{idx}[0][1]), color=RED, radius=0.1)",
                f"self.play(FadeIn(_dot{idx}))",
                f"for _xt, _yt in _traj{idx}[1:]:",
                f"    _ndot = Dot(_axes{idx}.c2p(_xt, _yt), color=RED, radius=0.1)",
                f"    _garr = Arrow(_dot{idx}.get_center(), _axes{idx}.c2p(_xt, _yt), buff=0.05, stroke_width=2, max_tip_length_to_length_ratio=0.3, color=YELLOW)",
                f"    self.play(Create(_garr), run_time=0.35)",
                f"    self.play(ReplacementTransform(_dot{idx}, _ndot), run_time=0.45)",
                f"    self.remove(_garr)",
                f"    _dot{idx} = _ndot",
                f"self.wait(1.5)",
            ]
            group_parts = [f"_axes{idx}", f"_curve{idx}", f"_dot{idx}"]
            if title_var:
                group_parts.insert(0, title_var)
            lines.append(f"{v} = VGroup({', '.join(group_parts)})")

        elif isinstance(beat, EigendecompositionBeat):
            n = len(beat.matrix)
            labels = beat.labels or [f"e{i+1}" for i in range(len(beat.eigenvalues))]

            # Normalise matrix to [0,1] for heatmap colouring
            flat = [val for row in beat.matrix for val in row]
            mn, mx = min(flat), max(flat)
            spread = max(mx - mn, 1e-9)
            norm_matrix = [[(val - mn) / spread for val in row] for row in beat.matrix]
            norm_r = repr([[round(val, 4) for val in row] for row in norm_matrix])
            idx_labels = [str(i) for i in range(n)]
            rl_r = repr(idx_labels)

            lines = [f"# Beat {idx+1}: eigendecomposition ({n}×{n})"]
            title_var = ""
            if beat.title:
                title_var = f"_edt{idx}"
                lines += [
                    f'{title_var} = Text("{_safe_str(beat.title)}", font_size=20)'
                    f".move_to(CONTENT_CENTER + UP*1.85)",
                    f"self.play(FadeIn({title_var}))",
                ]
            lines += [
                f"_mat{idx} = heatmap({norm_r}, row_labels={rl_r}, col_labels={rl_r},"
                f" center=LEFT_CENTER + UP*0.2)",
                f"self.play(FadeIn(_mat{idx}), run_time=0.8)",
                f"self.wait(0.4)",
            ]
            all_parts = [f"_mat{idx}"]

            if n == 2 and len(beat.eigenvectors) >= 1:
                lines += [
                    f'_axes{idx} = Axes(x_range=[-2, 2, 1], y_range=[-2, 2, 1], x_length=3.8, y_length=3.8, axis_config={{"color": GREY_B, "tip_length": 0.12}})',
                    f"_axes{idx}.move_to(RIGHT_CENTER + DOWN*0.2)",
                    f"self.play(Create(_axes{idx}))",
                ]
                all_parts.append(f"_axes{idx}")
                ev_colors = ["BLUE_C", "GREEN_C", "ORANGE", "PINK"]
                for j, evec in enumerate(beat.eigenvectors[:2]):
                    if len(evec) < 2:
                        continue
                    mag = max((evec[0]**2 + evec[1]**2) ** 0.5, 1e-9)
                    scale = min(1.5, 1.5 / (max(abs(evec[0]), abs(evec[1])) or 1))
                    ex = round(evec[0] * scale, 4)
                    ey = round(evec[1] * scale, 4)
                    col = ev_colors[j]
                    eval_val = beat.eigenvalues[j] if j < len(beat.eigenvalues) else 0.0
                    lbl_str = _safe_str(f"{labels[j]}={eval_val:.2f}")
                    side = "RIGHT" if ex >= 0 else "LEFT"
                    lines += [
                        f"_evec{idx}_{j} = Arrow(_axes{idx}.c2p(0,0), _axes{idx}.c2p({ex},{ey}),"
                        f" color={col}, buff=0, stroke_width=3)",
                        f"_elbl{idx}_{j} = Text(\"{lbl_str}\", font_size=16, color={col})"
                        f".next_to(_evec{idx}_{j}.get_end(), {side}, buff=0.08)",
                        f"self.play(Create(_evec{idx}_{j}), FadeIn(_elbl{idx}_{j}))",
                    ]
                    all_parts += [f"_evec{idx}_{j}", f"_elbl{idx}_{j}"]
            else:
                # 3×3: list eigenvalues as text
                eval_str = _safe_str(", ".join(
                    f"{labels[j]}={beat.eigenvalues[j]:.2f}"
                    for j in range(min(len(labels), len(beat.eigenvalues)))
                ))
                lines += [
                    f'_eval_txt{idx} = Text("Eigenvalues: {eval_str}", font_size=16, color=GREY_B)'
                    f".move_to(CONTENT_CENTER + UP*1.5)",
                    f"self.play(Write(_eval_txt{idx}))",
                ]
                all_parts.append(f"_eval_txt{idx}")

            lines.append("self.wait(2.5)")
            if title_var:
                all_parts.insert(0, title_var)
            lines.append(f"{v} = VGroup({', '.join(all_parts)})")

        elif isinstance(beat, TreeBeat):
            from collections import defaultdict as _dd, deque as _dq
            n_nodes = len(beat.nodes)
            children: dict = _dd(list)
            for edge in beat.edges:
                if len(edge) >= 2 and 0 <= edge[0] < n_nodes and 0 <= edge[1] < n_nodes:
                    children[edge[0]].append(edge[1])

            # BFS to assign levels
            root = 0
            level: dict = {root: 0}
            level_nodes: dict = _dd(list)
            queue = _dq([root])
            visited: set = {root}
            while queue:
                node = queue.popleft()
                level_nodes[level[node]].append(node)
                for child in children[node]:
                    if child not in visited:
                        level[child] = level[node] + 1
                        queue.append(child)
                        visited.add(child)
            for i in range(n_nodes):
                if i not in level:
                    lv = max(level.values()) + 1 if level else 0
                    level[i] = lv
                    level_nodes[lv].append(i)

            # Compute positions (Python, hardcoded in output)
            h_sp, v_sp = 1.5, 1.35
            positions: dict = {}
            for lv, lvnodes in level_nodes.items():
                w = (len(lvnodes) - 1) * h_sp
                for i, ni in enumerate(lvnodes):
                    positions[ni] = (round(-w / 2 + i * h_sp, 3), round(-lv * v_sp, 3))

            nc = _safe_color(beat.node_color or "BLUE", "BLUE")
            hc = _safe_color(beat.highlight_color or "YELLOW", "YELLOW")

            lines = [f"# Beat {idx+1}: tree"]
            title_var = ""
            if beat.title:
                title_var = f"_trt{idx}"
                lines += [
                    f'{title_var} = Text("{_safe_str(beat.title)}", font_size=20)'
                    f".move_to(CONTENT_CENTER + UP*1.85)",
                    f"self.play(FadeIn({title_var}))",
                ]
            lines.append(f"_tnodes{idx} = []")
            for i in range(n_nodes):
                x, y = positions.get(i, (0.0, 0.0))
                lbl = _safe_str(beat.nodes[i])
                lines += [
                    f"_nc{idx}_{i} = Circle(radius=0.28, color={nc}, fill_opacity=0.5, stroke_width=2)"
                    f".move_to(CONTENT_CENTER + RIGHT*{x} + UP*{y} + DOWN*0.4)",
                    f"_nt{idx}_{i} = Text(\"{lbl}\", font_size=15).move_to(_nc{idx}_{i}.get_center())",
                    f"_tnodes{idx}.append(VGroup(_nc{idx}_{i}, _nt{idx}_{i}))",
                ]
            lines.append(f"_tedges{idx} = VGroup()")
            for edge in beat.edges:
                if len(edge) >= 2 and 0 <= edge[0] < n_nodes and 0 <= edge[1] < n_nodes:
                    pi, ci = edge[0], edge[1]
                    lines.append(
                        f"_tedges{idx}.add(Line(_nc{idx}_{pi}.get_bottom(),"
                        f" _nc{idx}_{ci}.get_top(), color=GREY_B, stroke_width=1.5))"
                    )
            lines += [
                f"self.play(LaggedStart(*[Create(n) for n in _tnodes{idx}], lag_ratio=0.1))",
                f"self.play(LaggedStart(*[Create(e) for e in _tedges{idx}], lag_ratio=0.08))",
            ]
            if beat.traversal_order:
                valid_trav = [i for i in beat.traversal_order if 0 <= i < n_nodes]
                for ti in valid_trav:
                    lines += [
                        f"self.play(Indicate(_nc{idx}_{ti}, scale_factor=1.35, color={hc}))",
                        f"self.wait(0.4)",
                    ]
            lines.append("self.wait(1.5)")
            all_parts = [f"VGroup(*_tnodes{idx})", f"_tedges{idx}"]
            if title_var:
                all_parts.insert(0, title_var)
            lines.append(f"{v} = VGroup({', '.join(all_parts)})")

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
    """Extract and validate AnimationSpec JSON from an LLM response string.

    Tries multiple strategies in order:
    1. Direct parse (model returned only JSON)
    2. Fenced ```json ... ``` block
    3. Slice from first { to last } (object extraction)
    4. Greedy regex fallback
    """
    text = raw.strip()

    # 1. Direct parse
    try:
        return AnimationSpec.model_validate_json(text)
    except Exception:
        pass

    # 2. Fenced JSON block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return AnimationSpec.model_validate_json(m.group(1))
        except Exception:
            pass

    # 3. Slice first { to last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidate = text[start:end + 1]
        try:
            return AnimationSpec.model_validate_json(candidate)
        except Exception:
            pass

    # 4. Greedy regex fallback
    m2 = re.search(r"(\{.*\})", text, re.DOTALL)
    if m2:
        return AnimationSpec.model_validate_json(m2.group(1))

    raise ValueError("No valid AnimationSpec JSON found in LLM response")
