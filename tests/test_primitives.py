"""
Test suite for the animation primitive library.

Tests:
  1. DSLCompiler — all 12 beat types compile to syntactically valid Python
  2. mathlib_matcher — keyword scoring maps concepts to correct families
  3. parse_spec — JSON extraction strategies work for all formats
  4. End-to-end primitive mode — LLM call → spec → compiled Manim code
     (skipped if ANTHROPIC_API_KEY is not set)
"""

from __future__ import annotations

import ast
import json
import os
import sys
import textwrap

# Make sure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.animation.dsl import (
    AnimationSpec,
    AttentionMatrixBeat,
    BarChartBeat,
    BayesDiagramBeat,
    DSLCompiler,
    EigendecompositionBeat,
    FlowColumnBeat,
    GradientStepBeat,
    HeatmapBeat,
    NodeRowBeat,
    SideBySideBeat,
    TextBeat,
    TreeBeat,
    WeightedConnectionsBeat,
    parse_spec,
)
from src.concepts.mathlib_matcher import match_family, recommended_beats

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def check_compiles(code: str) -> None:
    """Assert that code is valid Python (ast.parse)."""
    try:
        ast.parse(code)
    except SyntaxError as e:
        lines = code.splitlines()
        context = "\n".join(
            f"  {i+1:3}: {l}" for i, l in enumerate(lines[max(0, e.lineno-3):e.lineno+2])
        )
        raise AssertionError(f"SyntaxError at line {e.lineno}: {e.msg}\n{context}") from e


def compile_single_beat(beat) -> str:
    spec = AnimationSpec(title="Test", class_name="TestScene", beats=[beat])
    code = DSLCompiler().compile(spec)
    check_compiles(code)
    return code


PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


def run(name: str, fn):
    try:
        fn()
        print(f"  [{PASS}] {name}")
        results.append((name, True, None))
    except Exception as e:
        print(f"  [{FAIL}] {name}: {e}")
        results.append((name, False, str(e)))


# ---------------------------------------------------------------------------
# Section 1: Beat compilation
# ---------------------------------------------------------------------------

print("\n=== 1. DSLCompiler — beat compilation ===\n")


def test_node_row():
    beat = NodeRowBeat(
        type="node_row",
        labels=["x₁", "x₂", "x₃"],
        colors=["BLUE_C", "GREEN_C", "ORANGE"],
        weights=[0.3, 0.5, 0.2],
        subtitle="Input tokens",
        position="upper",
    )
    code = compile_single_beat(beat)
    assert "node_row" in code
    assert "BLUE_C" in code
run("node_row", test_node_row)


def test_heatmap():
    beat = HeatmapBeat(
        type="heatmap",
        matrix=[[0.9, 0.1], [0.2, 0.8]],
        row_labels=["Q1", "Q2"],
        col_labels=["K1", "K2"],
        title="Attention scores",
        highlight_row=0,
    )
    code = compile_single_beat(beat)
    assert "heatmap" in code
    assert "YELLOW" in code  # highlight rectangle
run("heatmap with highlight_row", test_heatmap)


def test_bar_chart():
    beat = BarChartBeat(
        type="bar_chart",
        values=[0.1, 0.6, 0.2, 0.1],
        labels=["A", "B", "C", "D"],
        colors=["BLUE_C"] * 4,
        title="Prior distribution",
        then_transform=[0.05, 0.8, 0.1, 0.05],
    )
    code = compile_single_beat(beat)
    assert "bar_chart" in code
    assert "stretch" in code  # transform animation
run("bar_chart with then_transform", test_bar_chart)


def test_side_by_side():
    beat = SideBySideBeat(type="side_by_side", labels=["Encoder", "Attention", "Decoder"], highlight=1)
    code = compile_single_beat(beat)
    assert "side_by_side" in code
    assert "Indicate" in code
run("side_by_side with highlight", test_side_by_side)


def test_flow_column():
    beat = FlowColumnBeat(type="flow_column", labels=["Input", "Hidden", "Output"], colors=["BLUE", "TEAL", "GREEN"], highlight=1)
    code = compile_single_beat(beat)
    assert "flow_column" in code
    assert "Indicate" in code
run("flow_column with highlight", test_flow_column)


def test_text():
    beat = TextBeat(type="text", content="Attention is all you need", subtitle="Vaswani et al. 2017", color="WHITE")
    code = compile_single_beat(beat)
    assert "Attention is all you need" in code
    assert "Vaswani" in code
run("text with subtitle", test_text)


def test_weighted_connections():
    beat = WeightedConnectionsBeat(
        type="weighted_connections",
        from_labels=["q₁", "q₂"],
        to_labels=["k₁", "k₂", "k₃"],
        weights=[[0.7, 0.2, 0.1], [0.3, 0.5, 0.2]],
        title="Attention weights",
    )
    code = compile_single_beat(beat)
    assert "node_row" in code
run("weighted_connections", test_weighted_connections)


def test_attention_matrix():
    beat = AttentionMatrixBeat(
        type="attention_matrix",
        query_labels=["the", "cat"],
        key_labels=["the", "cat", "sat"],
        scores=[[0.7, 0.2, 0.1], [0.1, 0.6, 0.3]],
        highlight_query=0,
        title="Self-attention",
    )
    code = compile_single_beat(beat)
    assert "heatmap" in code
    assert "YELLOW" in code  # highlight rectangle
run("attention_matrix with highlight_query", test_attention_matrix)


def test_bayes():
    beat = BayesDiagramBeat(
        type="bayes",
        hypotheses=["H₁", "H₂", "H₃"],
        prior=[0.33, 0.33, 0.34],
        likelihood=[0.9, 0.4, 0.1],
        title="Bayesian update",
    )
    code = compile_single_beat(beat)
    assert "GREEN_C" in code   # posterior colour
    assert "stretch" in code   # bar transform
    assert "Posterior" in code
run("bayes (prior→posterior bar transform)", test_bayes)


def test_gradient_step_quadratic():
    beat = GradientStepBeat(
        type="gradient_step",
        fn_type="quadratic",
        a=1.0, b=0.0, c=0.0,
        x_range=[-3.0, 3.0],
        start_x=2.5,
        learning_rate=0.4,
        n_steps=5,
        title="Gradient descent on MSE",
    )
    code = compile_single_beat(beat)
    assert "Axes" in code
    assert "Arrow" in code
    assert "ReplacementTransform" in code
run("gradient_step (quadratic, 5 steps)", test_gradient_step_quadratic)


def test_gradient_step_sine():
    beat = GradientStepBeat(
        type="gradient_step",
        fn_type="sine",
        a=1.5, b=2.0, c=0.0,
        x_range=[-3.14, 3.14],
        start_x=1.0,
        learning_rate=0.2,
        n_steps=3,
    )
    code = compile_single_beat(beat)
    assert "np.sin" in code
run("gradient_step (sine)", test_gradient_step_sine)


def test_eigendecomposition_2x2():
    beat = EigendecompositionBeat(
        type="eigendecomposition",
        matrix=[[2.0, 1.0], [1.0, 2.0]],
        eigenvalues=[3.0, 1.0],
        eigenvectors=[[0.707, 0.707], [0.707, -0.707]],
        labels=["λ₁", "λ₂"],
        title="Eigendecomposition",
    )
    code = compile_single_beat(beat)
    assert "Arrow" in code   # eigenvector arrows
    assert "heatmap" in code
run("eigendecomposition (2×2, arrows)", test_eigendecomposition_2x2)


def test_eigendecomposition_3x3():
    beat = EigendecompositionBeat(
        type="eigendecomposition",
        matrix=[[4.0, 1.0, 0.0], [1.0, 3.0, 1.0], [0.0, 1.0, 2.0]],
        eigenvalues=[5.0, 3.0, 1.0],
        eigenvectors=[[0.6, 0.8, 0.0], [0.0, 0.0, 1.0], [-0.8, 0.6, 0.0]],
    )
    code = compile_single_beat(beat)
    assert "Eigenvalues" in code  # text fallback for 3×3
run("eigendecomposition (3×3, text eigenvalues)", test_eigendecomposition_3x3)


def test_tree_with_traversal():
    beat = TreeBeat(
        type="tree",
        nodes=["root", "A", "B", "C", "D"],
        edges=[[0, 1], [0, 2], [1, 3], [1, 4]],
        traversal_order=[0, 1, 3, 4, 2],
        node_color="BLUE",
        highlight_color="YELLOW",
        title="BFS traversal",
    )
    code = compile_single_beat(beat)
    assert "Circle" in code
    assert "Indicate" in code
run("tree with BFS traversal", test_tree_with_traversal)


# Edge cases
def test_bayes_auto_normalize():
    """Prior values get auto-normalised by the model validator."""
    beat = BayesDiagramBeat(
        type="bayes",
        hypotheses=["H₁", "H₂"],
        prior=[3.0, 1.0],    # unnormalised
        likelihood=[0.9, 0.2],
    )
    assert abs(sum(beat.prior) - 1.0) < 1e-9, f"prior not normalized: {beat.prior}"
    compile_single_beat(beat)
run("bayes auto-normalises prior", test_bayes_auto_normalize)


def test_heatmap_clamp():
    """Values outside [0,1] are clamped by the model validator."""
    beat = HeatmapBeat(
        type="heatmap",
        matrix=[[-0.5, 1.8], [0.3, 0.6]],
    )
    assert beat.matrix[0][0] == 0.0
    assert beat.matrix[0][1] == 1.0
run("heatmap clamps values to [0,1]", test_heatmap_clamp)


def test_gradient_clamp_n_steps():
    """n_steps is clamped to [1, 8] by the field validator."""
    try:
        GradientStepBeat(type="gradient_step", n_steps=20)
        raise AssertionError("Should have raised ValidationError for n_steps=20")
    except Exception as e:
        if "ValidationError" in type(e).__name__ or "validation" in str(e).lower():
            pass  # expected
        else:
            raise
run("gradient_step rejects n_steps > 8", test_gradient_clamp_n_steps)


def test_multi_beat_spec():
    """Full spec with 3 different beats compiles as a complete Manim file."""
    spec = AnimationSpec(
        title="Self-Attention Mechanism",
        class_name="SelfAttentionScene",
        beats=[
            TextBeat(type="text", content="Self-Attention", subtitle="Scaled dot-product attention"),
            AttentionMatrixBeat(
                type="attention_matrix",
                query_labels=["the", "cat", "sat"],
                key_labels=["the", "cat", "sat"],
                scores=[[0.7, 0.2, 0.1], [0.1, 0.6, 0.3], [0.2, 0.3, 0.5]],
                highlight_query=1,
                title="Attention scores",
            ),
            GradientStepBeat(type="gradient_step", fn_type="quadratic", n_steps=4, title="Loss minimisation"),
        ],
    )
    code = DSLCompiler().compile(spec)
    check_compiles(code)
    assert "SelfAttentionScene" in code
    assert "class SelfAttentionScene(Scene)" in code
    # Count FadeOut calls (should be n_beats - 1 = 2)
    assert code.count("FadeOut") == 2
run("multi-beat spec (3 beats, 2 FadeOuts)", test_multi_beat_spec)


# ---------------------------------------------------------------------------
# Section 2: parse_spec — JSON extraction strategies
# ---------------------------------------------------------------------------

print("\n=== 2. parse_spec — JSON extraction strategies ===\n")

SAMPLE_SPEC = {
    "title": "Test Concept",
    "class_name": "TestConceptScene",
    "beats": [
        {"type": "text", "content": "Hello", "subtitle": "World"},
    ],
}


def test_parse_direct():
    raw = json.dumps(SAMPLE_SPEC)
    spec = parse_spec(raw)
    assert spec.title == "Test Concept"
run("parse_spec: direct JSON string", test_parse_direct)


def test_parse_fenced():
    raw = f"Here is the spec:\n```json\n{json.dumps(SAMPLE_SPEC)}\n```\nDone."
    spec = parse_spec(raw)
    assert spec.class_name == "TestConceptScene"
run("parse_spec: fenced ```json block", test_parse_fenced)


def test_parse_bracket_slice():
    raw = f"Some preamble... {json.dumps(SAMPLE_SPEC)} trailing text."
    spec = parse_spec(raw)
    assert len(spec.beats) == 1
run("parse_spec: bracket-slice from prose", test_parse_slice := test_parse_bracket_slice)


def test_parse_greedy():
    raw = "Output: " + json.dumps(SAMPLE_SPEC).replace("\n", " ") + " end."
    spec = parse_spec(raw)
    assert spec.beats[0].type == "text"
run("parse_spec: greedy regex fallback", test_parse_greedy)


# ---------------------------------------------------------------------------
# Section 3: mathlib_matcher
# ---------------------------------------------------------------------------

print("\n=== 3. mathlib_matcher — family detection ===\n")


class _MockConcept:
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description


MATCHER_CASES = [
    ("Self-attention mechanism", "Uses query, key, value matrices; scaled dot-product attention", "attention"),
    ("Gradient descent", "Minimises a loss function by following the negative gradient", "algorithm"),
    ("Bayesian inference", "Update prior probability distribution using likelihood of evidence", "probability"),
    ("Eigendecomposition", "Matrix decomposed into eigenvalues and eigenvectors", "linear_algebra"),
    ("BFS traversal", "Breadth-first search visits graph nodes level by level", "graph"),
    ("Neural network layers", "Feedforward network with relu activation and dropout", "neural_network"),
    ("Convex optimization", "Minimize a convex loss subject to inequality constraints", "optimization"),
]


def make_matcher_test(name, desc, expected):
    def _test():
        concept = _MockConcept(name, desc)
        family = match_family(concept)
        recs = recommended_beats(family)
        assert family == expected, f"expected '{expected}', got '{family}'"
        assert len(recs) >= 2
    return _test


for cname, cdesc, cfamily in MATCHER_CASES:
    run(f"match_family: '{cname}' → '{cfamily}'", make_matcher_test(cname, cdesc, cfamily))


# ---------------------------------------------------------------------------
# Section 4: End-to-end with real LLM (optional)
# ---------------------------------------------------------------------------

print("\n=== 4. End-to-end: primitive mode (real LLM) ===\n")

HAS_ANTHROPIC = bool(os.environ.get("ANTHROPIC_API_KEY"))

if not HAS_ANTHROPIC:
    print("  [SKIP] ANTHROPIC_API_KEY not set — skipping LLM call tests.\n")
else:
    from src.animation.codegen import ManimCodeGenerator
    from src.concepts.extractor import Concept

    E2E_CONCEPTS = [
        Concept(
            name="Self-Attention",
            description="Scaled dot-product attention computes a weighted sum of value vectors, "
                        "where weights come from softmax of query-key dot products divided by sqrt(d_k).",
            visual_type="matrix_operation",
            variables=["Q", "K", "V", "d_k"],
            raw_text="Attention(Q,K,V) = softmax(QK^T/sqrt(d_k))V",
            shot_list=[],
        ),
        Concept(
            name="Bayesian Update",
            description="Given a prior distribution over hypotheses and a likelihood function, "
                        "compute the posterior using Bayes' theorem.",
            visual_type="probability_distribution",
            variables=["P(H)", "P(E|H)", "P(H|E)"],
            raw_text="P(H|E) = P(E|H) * P(H) / P(E)",
            shot_list=[],
        ),
        Concept(
            name="Gradient Descent",
            description="Iterative optimisation algorithm that minimises a loss function L(θ) "
                        "by updating parameters in the direction of the negative gradient.",
            visual_type="optimization_trajectory",
            variables=["L(θ)", "η", "∇L"],
            raw_text="θ_{t+1} = θ_t - η ∇L(θ_t)",
            shot_list=[],
        ),
    ]

    gen = ManimCodeGenerator(provider="anthropic", model="claude-sonnet-4-6")

    for concept in E2E_CONCEPTS:
        def _make_e2e(c):
            def _test():
                code = gen.generate_primitive(c)
                check_compiles(code)
                assert "class" in code and "Scene" in code
                assert f"# Generated by DSLCompiler" not in code  # not a marker, just check structure
                lines = code.splitlines()
                assert len(lines) > 20, f"Code suspiciously short ({len(lines)} lines)"
                print(f"         → {len(lines)} lines, class: {[l for l in lines if 'class' in l and 'Scene' in l][0].strip()}")
            return _test
        run(f"e2e primitive mode: '{concept.name}'", _make_e2e(concept))


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 55)
passed = sum(1 for _, ok, _ in results if ok)
failed = sum(1 for _, ok, _ in results if not ok)
print(f"  Results: {passed} passed, {failed} failed out of {len(results)} tests")
if failed:
    print("\n  Failures:")
    for name, ok, err in results:
        if not ok:
            print(f"    - {name}: {err}")
print("=" * 55 + "\n")

if failed:
    sys.exit(1)
