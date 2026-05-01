"""
Static validator for generated Manim code.

Catches spatial mistakes before rendering so the fix loop gets a precise,
actionable error message rather than a cryptic runtime traceback.
"""

from __future__ import annotations

import ast
import re


def validate(code: str) -> list[str]:
    """
    Run all checks. Returns list of issue strings; empty = clean.
    Each issue is one concrete, fix-actionable sentence.
    """
    issues: list[str] = []
    issues.extend(_check_arrow_endpoints(code))
    issues.extend(_check_hardcoded_move_to(code))
    issues.extend(_check_next_to_origin(code))
    issues.extend(_check_overlapping_text_placement(code))
    return issues


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_arrow_endpoints(code: str) -> list[str]:
    """
    Arrow/Line/CurvedArrow endpoints should come from object boundary methods
    (.get_right, .get_left, .get_top, .get_bottom, .get_center, .get_corner)
    or from the connect()/connect_curved() helpers.
    Hardcoded direction vectors (LEFT*2, UP+RIGHT, np.array([...])) are wrong.
    """
    issues = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    arrow_types = {"Arrow", "Line", "CurvedArrow", "DashedLine", "DoubleArrow"}
    get_methods = {
        "get_right", "get_left", "get_top", "get_bottom",
        "get_center", "get_corner", "get_edge_center",
        "get_start", "get_end", "get_boundary_point",
        "c2p",  # axes coordinate conversion
    }
    safe_call_names = {"connect", "connect_curved", "np", "array"}

    hardcoded: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = _call_name(node)
        if func_name not in arrow_types:
            continue
        # Check first two positional args (start, end points)
        for arg in node.args[:2]:
            if _is_hardcoded_vector(arg, get_methods, safe_call_names):
                hardcoded.append(func_name)
                break

    if hardcoded:
        count = len(hardcoded)
        issues.append(
            f"{count} Arrow/Line call(s) use hardcoded direction vectors as endpoints "
            f"(e.g. LEFT*2, UP+RIGHT, ORIGIN). "
            "Use obj.get_right(), obj.get_left(), obj.get_top(), obj.get_bottom(), "
            "or the connect(obj_a, obj_b) helper instead. "
            "Never pass bare direction constants as Arrow start/end points."
        )
    return issues


def _check_hardcoded_move_to(code: str) -> list[str]:
    """
    .move_to([x, y, z]) with numeric literals is fragile — objects won't
    stay aligned when other objects shift. Positions should be derived from
    other objects or from arithmetic on ORIGIN/UP/RIGHT/etc.
    """
    # Match .move_to( followed by a list literal with numbers
    pattern = re.compile(r'\.move_to\s*\(\s*\[\s*-?\d', re.MULTILINE)
    hits = pattern.findall(code)
    if hits:
        return [
            f"move_to([x, y, z]) with raw numeric coordinates found ({len(hits)} instance(s)). "
            "Derive positions from other objects: use .next_to(obj, direction), "
            ".move_to(obj.get_center() + offset), or arithmetic like ORIGIN + RIGHT*2 + UP*0.5."
        ]
    return []


def _check_next_to_origin(code: str) -> list[str]:
    """
    .next_to(ORIGIN, ...) or .next_to(UP, ...) etc. places objects relative
    to a fixed point, not another mobject — layout breaks when anything moves.
    """
    # Match .next_to( followed by a direction constant (not an object)
    pattern = re.compile(
        r'\.next_to\s*\(\s*(?:ORIGIN|UP|DOWN|LEFT|RIGHT|UL|UR|DL|DR)\s*[,\)]',
        re.MULTILINE,
    )
    hits = pattern.findall(code)
    if hits:
        return [
            f"next_to() called with a direction constant instead of a mobject "
            f"({len(hits)} instance(s)). "
            "Pass the target mobject as the first argument: obj.next_to(other_obj, DOWN, buff=0.2)."
        ]
    return []


def _check_overlapping_text_placement(code: str) -> list[str]:
    """
    Multiple Text objects placed at the same hardcoded position will overlap.
    Heuristic: if more than 3 Text/move_to calls use identical numeric y-values.
    """
    # Find all move_to([x, y, ...]) and extract y values
    pattern = re.compile(r'move_to\s*\(\s*\[\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)', re.MULTILINE)
    y_values: list[str] = []
    for m in pattern.finditer(code):
        y_values.append(m.group(2))

    from collections import Counter
    for y, count in Counter(y_values).items():
        if count >= 3:
            return [
                f"{count} objects share the same hardcoded y-coordinate ({y}). "
                "They will overlap. Use .arrange(), .next_to(), or offset each by index: "
                "obj.move_to(base + UP * i * spacing)."
            ]
    return []


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _call_name(node: ast.Call) -> str:
    """Extract simple function name from a Call node."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _is_hardcoded_vector(node: ast.expr, get_methods: set[str], safe_names: set[str]) -> bool:
    """
    Return True if `node` looks like a hardcoded direction vector rather than
    a boundary method call on a mobject.
    """
    # Safe: attribute call like obj.get_right()
    if isinstance(node, ast.Call):
        name = _call_name(node)
        if name in get_methods or name in safe_names:
            return False
        # Safe: connect(a, b) or similar helper
        if isinstance(node.func, ast.Name) and node.func.id in safe_names:
            return False

    # Hardcoded: bare Name that's a Manim direction constant (UP, DOWN, LEFT, RIGHT, ORIGIN, etc.)
    direction_constants = {
        "UP", "DOWN", "LEFT", "RIGHT", "ORIGIN",
        "UL", "UR", "DL", "DR", "IN", "OUT",
    }
    if isinstance(node, ast.Name) and node.id in direction_constants:
        return True

    # Hardcoded: BinOp like LEFT*2, UP+RIGHT*0.5 — both sides are direction constants or numbers
    if isinstance(node, ast.BinOp):
        left_hard = _is_hardcoded_vector(node.left, get_methods, safe_names)
        right_is_scalar = isinstance(node.right, (ast.Constant, ast.UnaryOp))
        right_hard = _is_hardcoded_vector(node.right, get_methods, safe_names)
        if left_hard and (right_is_scalar or right_hard):
            return True
        if right_hard and isinstance(node.left, (ast.Constant, ast.UnaryOp)):
            return True

    # Hardcoded: np.array([x, y, z])
    if isinstance(node, ast.Call):
        if _call_name(node) == "array":
            return True

    return False
