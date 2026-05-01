"""
Layout helper functions for Manim scene generation.

These are auto-injected into every generated scene. The model calls these
instead of computing positions manually — eliminates arrow endpoint errors
and centering mistakes.
"""

from manim import *
import numpy as np

# Safe content zone — all non-title objects must stay within this area.
# The title occupies the top ~1.2 units (to_edge(UP) + font height).
# CONTENT_TOP marks the ceiling; CONTENT_CENTER is the natural anchor for
# helpers whose `center` parameter defaults to ORIGIN.
CONTENT_TOP = UP * 2.7       # highest y any non-title object should reach
CONTENT_CENTER = DOWN * 0.5  # center of the content safe zone (use as `center=` default)

# Convenience anchors — common offsets from content center
LEFT_CENTER = CONTENT_CENTER + LEFT * 3.2
RIGHT_CENTER = CONTENT_CENTER + RIGHT * 3.2


def node_row(labels, colors=None, center=ORIGIN, spacing=1.5, radius=0.32, stage_colors=None):
    """
    Horizontal row of filled circles with centered text labels.
    Positions are computed from center outward — never hardcoded.

    Returns: (circles: VGroup, texts: VGroup)

    Example:
        circles, texts = node_row(["Q", "K", "V"], [GREEN, ORANGE, RED])
        self.play(LaggedStart(*[FadeIn(c) for c in circles], lag_ratio=0.2))
    """
    colors = colors if colors is not None else stage_colors
    n = len(labels)
    if colors is None:
        colors = [BLUE] * n
    elif not isinstance(colors, (list, tuple)):
        colors = [colors] * n
    xs = [(i - (n - 1) / 2) * spacing for i in range(n)]
    circles = VGroup(*[
        Circle(radius=radius, color=colors[i], fill_color=colors[i], fill_opacity=0.75)
        .move_to(center + RIGHT * xs[i])
        for i in range(n)
    ])
    texts = VGroup(*[
        Text(str(labels[i]), font_size=20).move_to(circles[i])
        for i in range(n)
    ])
    return circles, texts


def flow_column(stage_labels, stage_colors=None, center=ORIGIN,
                box_width=5.2, box_height=0.68, v_spacing=1.15, colors=None):
    """
    Vertical stack of RoundedRectangles with connecting arrows.
    Arrows use .get_bottom()/.get_top() — never hardcoded vectors.

    Returns: (boxes: list[VGroup], arrows: list[Arrow])
    Each box is VGroup(rect, text), moveable as a unit.

    Example:
        boxes, arrows = flow_column(
            ["Encoder", "Attention", "Decoder"],
            [BLUE, TEAL, ORANGE]
        )
        self.play(LaggedStart(*[FadeIn(b) for b in boxes], lag_ratio=0.25))
        self.play(LaggedStart(*[Create(a) for a in arrows], lag_ratio=0.3))
    """
    n = len(stage_labels)
    stage_colors = stage_colors if stage_colors is not None else colors
    if stage_colors is None:
        stage_colors = [BLUE] * n
    elif not isinstance(stage_colors, (list, tuple)):
        stage_colors = [stage_colors] * n
    total_h = (n - 1) * v_spacing
    positions = [center + UP * (total_h / 2 - i * v_spacing) for i in range(n)]

    boxes = []
    for label, color, pos in zip(stage_labels, stage_colors, positions):
        rect = RoundedRectangle(
            width=box_width, height=box_height, corner_radius=0.12,
            color=color, fill_color=color, fill_opacity=0.18,
        )
        txt = Text(label, font_size=21).move_to(rect)
        boxes.append(VGroup(rect, txt).move_to(pos))

    arrows = VGroup(*[
        Arrow(boxes[i].get_bottom(), boxes[i + 1].get_top(), buff=0.07, stroke_width=2)
        for i in range(n - 1)
    ])
    return boxes, arrows


def connect(obj_a, obj_b, color=WHITE, stroke_width=2, buff=0.1):
    """
    Arrow between two mobjects using their actual boundary points.
    Automatically picks horizontal (RIGHT→LEFT) or vertical (BOTTOM→TOP) axis.

    Example:
        arr = connect(encoder_box, decoder_box, color=BLUE)
        self.play(Create(arr))
    """
    a_c = obj_a.get_center()
    b_c = obj_b.get_center()
    if abs(b_c[0] - a_c[0]) >= abs(b_c[1] - a_c[1]):
        start, end = obj_a.get_right(), obj_b.get_left()
    elif b_c[1] < a_c[1]:
        start, end = obj_a.get_bottom(), obj_b.get_top()
    else:
        start, end = obj_a.get_top(), obj_b.get_bottom()
    return Arrow(start, end, buff=buff, color=color, stroke_width=stroke_width)


def connect_curved(obj_a, obj_b, angle=TAU / 4, color=WHITE, stroke_width=2):
    """
    Curved arrow between two mobjects using actual boundary points.

    Example:
        fb = connect_curved(decoder_box, encoder_box, angle=TAU/3, color=RED)
        self.play(Create(fb))
    """
    a_c = obj_a.get_center()
    b_c = obj_b.get_center()
    if abs(b_c[0] - a_c[0]) >= abs(b_c[1] - a_c[1]):
        start = obj_a.get_right() if b_c[0] > a_c[0] else obj_a.get_left()
        end = obj_b.get_left() if b_c[0] > a_c[0] else obj_b.get_right()
    else:
        start = obj_a.get_top() if b_c[1] > a_c[1] else obj_a.get_bottom()
        end = obj_b.get_bottom() if b_c[1] > a_c[1] else obj_b.get_top()
    return CurvedArrow(start, end, angle=angle, color=color, stroke_width=stroke_width)


def heatmap(matrix, row_labels=None, col_labels=None, cell_size=0.62, center=ORIGIN,
            low_color=BLUE, high_color=BLUE):
    """
    Attention-style heatmap. Values in [0, 1]; higher → more opaque.
    Returns a VGroup containing all cells and labels, centered at `center`.

    Example:
        weights = [[0.1, 0.7, 0.2], [0.4, 0.4, 0.2], [0.05, 0.9, 0.05]]
        grid = heatmap(weights, row_labels=["Q1","Q2","Q3"], col_labels=["K1","K2","K3"])
        self.play(FadeIn(grid))
    """
    rows, cols = len(matrix), len(matrix[0])
    group = VGroup()

    for r in range(rows):
        for c in range(cols):
            val = float(np.clip(matrix[r][c], 0, 1))
            pos = center + RIGHT * (c - (cols - 1) / 2) * cell_size \
                         + UP * ((rows - 1) / 2 - r) * cell_size
            cell = Rectangle(
                width=cell_size - 0.04, height=cell_size - 0.04,
                fill_color=BLUE, fill_opacity=max(0.08, val),
                stroke_color=WHITE, stroke_width=0.5,
            ).move_to(pos)
            val_lbl = Text(f"{val:.2f}", font_size=11, color=WHITE).move_to(cell)
            group.add(cell, val_lbl)

    # Column labels (above)
    grid_top = center + UP * (rows / 2) * cell_size
    for c, lbl in enumerate(col_labels or []):
        t = Text(str(lbl), font_size=15, color=GREY_B)
        t.move_to(grid_top + RIGHT * (c - (cols - 1) / 2) * cell_size + UP * 0.3)
        group.add(t)

    # Row labels (left)
    grid_left = center + LEFT * (cols / 2) * cell_size
    for r, lbl in enumerate(row_labels or []):
        t = Text(str(lbl), font_size=15, color=GREY_B)
        t.move_to(grid_left + UP * ((rows - 1) / 2 - r) * cell_size + LEFT * 0.35)
        group.add(t)

    return group


def side_by_side(stage_labels, stage_colors=None, center=ORIGIN,
                 box_width=2.6, box_height=1.4, h_spacing=3.8, colors=None):
    """
    Horizontal row of RoundedRectangles with left→right connecting arrows.
    Use this for encoder-decoder, input-output, or any left-to-right layout.
    flow_column is vertical; side_by_side is horizontal.

    Returns: (boxes: list[VGroup], arrows: list[Arrow])

    Example:
        boxes, arrows = side_by_side(["Encoder", "Decoder"], [BLUE, GREEN])
        self.play(LaggedStart(*[FadeIn(b) for b in boxes], lag_ratio=0.3))
        self.play(LaggedStart(*[Create(a) for a in arrows], lag_ratio=0.3))
    """
    n = len(stage_labels)
    stage_colors = stage_colors if stage_colors is not None else colors
    if stage_colors is None:
        stage_colors = [BLUE] * n
    elif not isinstance(stage_colors, (list, tuple)):
        stage_colors = [stage_colors] * n
    total_w = (n - 1) * h_spacing
    positions = [center + RIGHT * (i * h_spacing - total_w / 2) for i in range(n)]

    boxes = []
    for label, color, pos in zip(stage_labels, stage_colors, positions):
        rect = RoundedRectangle(
            width=box_width, height=box_height, corner_radius=0.12,
            color=color, fill_color=color, fill_opacity=0.18,
        )
        txt = Text(label, font_size=21).move_to(rect)
        boxes.append(VGroup(rect, txt).move_to(pos))

    arrows = VGroup(*[
        Arrow(boxes[i].get_right(), boxes[i + 1].get_left(), buff=0.07, stroke_width=2)
        for i in range(n - 1)
    ])
    return boxes, arrows


def bar_chart(values, labels, colors=None, max_height=3.2,
              bar_width=0.85, spacing=1.35, center=ORIGIN):
    """
    Build a bar chart anchored at center. All positions derived from center.
    Returns (bars: list[Rectangle], label_texts: list[Text], baseline: Line).

    To animate bars growing, use animate_bars(scene, bars, baseline).

    Example:
        bars, lbls, baseline = bar_chart([28.4, 35.0, 41.8],
                                         ["RNN", "ConvS2S", "Transformer"],
                                         [BLUE, GREEN, ORANGE])
        self.play(Create(baseline))
        animate_bars(self, bars, baseline)
        self.play(LaggedStart(*[FadeIn(l) for l in lbls], lag_ratio=0.15))
    """
    n = len(values)
    if colors is None:
        colors = [BLUE] * n
    elif not isinstance(colors, (list, tuple)):
        colors = [colors] * n
    max_val = max(values) if max(values) != 0 else 1
    baseline_y = center[1] - max_height / 2 - 0.2

    baseline = Line(
        LEFT * (n * spacing / 2 + 0.4) + UP * baseline_y,
        RIGHT * (n * spacing / 2 + 0.4) + UP * baseline_y,
        color=WHITE, stroke_width=2,
    )

    bars, label_texts = [], []
    for i, (val, label, color) in enumerate(zip(values, labels, colors)):
        h = max((val / max_val) * max_height, 0.02)
        x = (i - (n - 1) / 2) * spacing + center[0]
        bar = Rectangle(
            width=bar_width, height=h,
            fill_color=color, fill_opacity=0.85,
            stroke_color=color, stroke_width=1,
        ).align_to(UP * baseline_y, DOWN).shift(RIGHT * x)
        lbl = Text(str(label), font_size=14).next_to(
            UP * baseline_y + RIGHT * x, DOWN, buff=0.14
        )
        bars.append(bar)
        label_texts.append(lbl)

    return bars, label_texts, baseline


def animate_bars(scene, bars, baseline, lag_ratio=0.15, run_time=0.5):
    """
    Grow each bar from the baseline upward.
    Handles the add/transform/remove pattern automatically.

    Example:
        bars, lbls, baseline = bar_chart(...)
        scene.play(Create(baseline))
        animate_bars(scene, bars, baseline)
    """
    baseline_y = baseline.get_center()[1]
    flat_bars = []
    for bar in bars:
        flat = bar.copy().stretch_to_fit_height(0.001).align_to(UP * baseline_y, DOWN)
        scene.add(flat)
        flat_bars.append(flat)
    scene.play(LaggedStart(
        *[Transform(flat, bar, run_time=run_time) for flat, bar in zip(flat_bars, bars)],
        lag_ratio=lag_ratio,
    ))
    for flat, bar in zip(flat_bars, bars):
        scene.remove(flat)
        scene.add(bar)
