"""
Deterministic Manim scene generator for concept knowledge graphs.
No LLM involved — takes structured data, emits clean Python.
"""

from __future__ import annotations

import math
import textwrap


# Vivid palette — one bright color per visual type
_TYPE_COLORS = {
    "equation_transform": "BLUE_B",
    "geometric":          "GREEN_B",
    "number_flow":        "ORANGE",
    "weight_update":      "YELLOW",
    "matrix_op":          "TEAL",
    "diagram":            "PURPLE",
    "flow":               "RED",
    "graph":              "BLUE_C",
    "timeline":           "GREY_B",
}

# Shorter display labels for visual types
_TYPE_LABELS = {
    "equation_transform": "eq",
    "geometric":          "geo",
    "number_flow":        "flow",
    "weight_update":      "weight",
    "matrix_op":          "matrix",
    "diagram":            "diagram",
    "flow":               "flow",
    "graph":              "graph",
    "timeline":           "time",
}


def _circle_positions(n: int, radius: float) -> list[tuple[float, float]]:
    """Evenly spaced on a circle, starting from top-center."""
    return [
        (radius * math.cos(2 * math.pi * i / n - math.pi / 2),
         radius * math.sin(2 * math.pi * i / n - math.pi / 2))
        for i in range(n)
    ]


def _grid_positions(n: int, x_gap: float = 2.6, y_gap: float = 1.8) -> list[tuple[float, float]]:
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    pos = []
    for r in range(rows):
        for c in range(cols):
            if len(pos) < n:
                x = (c - (cols - 1) / 2) * x_gap
                y = ((rows - 1) / 2 - r) * y_gap
                pos.append((x, y))
    return pos


def generate_graph_scene(
    concepts: list[dict],
    edges: list[dict],
    title: str = "Concept Map",
) -> str:
    """
    Generate a polished Manim concept map scene.

    concepts: list of {name, visual_type, description}
    edges: list of {from: int, to: int, label: str}
    """
    n = len(concepts)
    if n == 0:
        return ""

    # Layout: circle for ≤8, grid otherwise; scale radius with count
    radius = max(2.4, min(3.4, 0.52 * n))
    if n <= 8:
        positions = _circle_positions(n, radius)
    else:
        positions = _grid_positions(n)

    # Shift all positions down slightly to make room for title
    positions = [(x, y - 0.3) for x, y in positions]

    node_lines = []
    for i, c in enumerate(concepts):
        name = c.get("name", f"Concept {i}")
        vtype = c.get("visual_type", "diagram")
        short = (name[:20] + "…") if len(name) > 20 else name
        color = _TYPE_COLORS.get(vtype, "GREY_B")
        type_label = _TYPE_LABELS.get(vtype, vtype)
        x, y = positions[i]
        node_lines.append(f'        ({x:.3f}, {y:.3f}, "{short}", {color}, "{type_label}"),')

    edge_lines = []
    for e in edges:
        src = int(e.get("from", 0))
        dst = int(e.get("to", 0))
        label = str(e.get("label", ""))[:22].replace('"', "'")
        if 0 <= src < n and 0 <= dst < n and src != dst:
            edge_lines.append(f'        ({src}, {dst}, "{label}"),')

    nodes_block  = "\n".join(node_lines)
    edges_block  = "\n".join(edge_lines) if edge_lines else "        # no edges"
    scene_title  = title[:40].replace('"', "'")

    code = textwrap.dedent(f'''\
        from manim import *
        import numpy as np

        class ConceptGraphScene(Scene):
            def construct(self):
                self.camera.background_color = "#0d0d1a"

                # (x, y, short_name, color, type_label)
                NODES = [
        {nodes_block}
                ]
                # (src_idx, dst_idx, relationship_label)
                EDGES = [
        {edges_block}
                ]

                # ── Title ──────────────────────────────────────────────────
                title = Text("{scene_title}", font_size=36, color=WHITE, weight=BOLD)
                title.to_edge(UP, buff=0.25)
                underline = Line(
                    title.get_left() + DOWN * 0.08,
                    title.get_right() + DOWN * 0.08,
                    stroke_width=1.5, color=BLUE_B,
                )
                underline.next_to(title, DOWN, buff=0.06)
                self.play(Write(title), Create(underline), run_time=1.0)
                self.wait(0.3)

                # ── Build nodes ────────────────────────────────────────────
                node_rings  = []   # outer glow ring
                node_fills  = []   # filled circle
                name_labels = []   # concept name text
                type_badges = []   # small type chip

                for (x, y, name, color, ttype) in NODES:
                    pos = np.array([x, y, 0])

                    # Outer glow ring
                    ring = Circle(radius=0.52, color=color,
                                  fill_opacity=0.0, stroke_width=1.2, stroke_opacity=0.4)
                    ring.move_to(pos)

                    # Filled circle
                    fill = Circle(radius=0.42, color=color,
                                  fill_opacity=0.55, stroke_width=2.5)
                    fill.move_to(pos)

                    # Name label — break into two lines if long
                    words = name.split()
                    if len(words) > 3:
                        mid = len(words) // 2
                        line1 = " ".join(words[:mid])
                        line2 = " ".join(words[mid:])
                        lbl = VGroup(
                            Text(line1, font_size=13, color=WHITE, weight=BOLD),
                            Text(line2, font_size=13, color=WHITE, weight=BOLD),
                        ).arrange(DOWN, buff=0.04)
                    else:
                        lbl = Text(name, font_size=14, color=WHITE, weight=BOLD)
                    lbl.move_to(pos + UP * 0.06)

                    # Type badge
                    badge_bg = RoundedRectangle(
                        corner_radius=0.06, width=0.58, height=0.20,
                        color=color, fill_opacity=0.35, stroke_width=0,
                    )
                    badge_text = Text(ttype, font_size=8, color=color)
                    badge_bg.next_to(fill, DOWN, buff=0.08)
                    badge_text.move_to(badge_bg.get_center())

                    node_rings.append(ring)
                    node_fills.append(fill)
                    name_labels.append(lbl)
                    type_badges.append(VGroup(badge_bg, badge_text))

                # Animate nodes in with staggered scale-in
                _n = len(NODES)
                self.play(
                    LaggedStart(
                        *[AnimationGroup(FadeIn(ring, scale=0.3), FadeIn(fill, scale=0.5))
                          for ring, fill in zip(node_rings, node_fills)],
                        lag_ratio=0.12,
                    ),
                    run_time=max(1.2, _n * 0.18),
                )
                self.play(
                    LaggedStart(*[Write(l) for l in name_labels], lag_ratio=0.08),
                    LaggedStart(*[FadeIn(b, scale=0.8) for b in type_badges], lag_ratio=0.08),
                    run_time=max(0.8, _n * 0.12),
                )
                self.wait(0.5)

                # ── Draw edges ─────────────────────────────────────────────
                edge_grp = VGroup()
                elabel_grp = VGroup()

                for (src, dst, rel) in EDGES:
                    src_pos = node_fills[src].get_center()
                    dst_pos = node_fills[dst].get_center()
                    src_color = NODES[src][3]  # inherit color from source node

                    arr = Arrow(
                        src_pos, dst_pos,
                        buff=0.46,
                        stroke_width=2.2,
                        color=src_color,
                        max_tip_length_to_length_ratio=0.14,
                        stroke_opacity=0.75,
                    )

                    # Edge label offset perpendicular to the edge direction
                    direction = dst_pos - src_pos
                    length = np.linalg.norm(direction)
                    if length > 0.001:
                        perp = np.array([-direction[1], direction[0], 0]) / length * 0.28
                    else:
                        perp = UP * 0.28
                    mid = (src_pos + dst_pos) / 2 + perp

                    elbl = Text(rel, font_size=10, color=src_color, slant=ITALIC)
                    bg = SurroundingRectangle(
                        elbl, buff=0.05, corner_radius=0.05,
                        color=src_color, fill_opacity=0.18, stroke_width=0.8,
                    )
                    elbl_group = VGroup(bg, elbl)
                    elbl_group.move_to(mid)

                    edge_grp.add(arr)
                    elabel_grp.add(elbl_group)

                if len(edge_grp) > 0:
                    self.play(
                        LaggedStart(*[Create(a) for a in edge_grp], lag_ratio=0.15),
                        run_time=max(1.0, len(edge_grp) * 0.25),
                    )
                    self.play(
                        LaggedStart(*[FadeIn(el) for el in elabel_grp], lag_ratio=0.10),
                        run_time=max(0.6, len(elabel_grp) * 0.15),
                    )

                # ── Pulse highlight each connected node pair ───────────────
                highlighted = set()
                for (src, dst, _) in EDGES:
                    highlighted.add(src)
                    highlighted.add(dst)

                if highlighted:
                    self.play(
                        *[Indicate(node_fills[i], color=NODES[i][3], scale_factor=1.15)
                          for i in highlighted],
                        run_time=1.2,
                    )

                self.wait(3.5)
    ''')

    return code
