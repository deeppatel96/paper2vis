"""
Phase 4: Lean / Mathlib grounded animation.

This module bridges paper2vis's animation primitive library with Lean 4's Mathlib
type hierarchy. It works at two levels:

1. **Structure Registry** (always available, no Lean install needed)
   A hardcoded mapping of ~30 key Mathlib types → their structural fields →
   suggested animation beats and parameterisation hints. When the concept
   matcher recognises a Lean type, the registry injects precise beat-level
   guidance into codegen rather than relying on coarse keyword heuristics.

2. **LeanClient** (optional, requires `lean` in PATH)
   A thin subprocess wrapper around `lean --stdin` for core-Lean type queries.
   If a Mathlib-enabled Lake project is available (`LEAN_PROJECT_PATH` env var),
   it can query arbitrary Mathlib definitions. Falls back gracefully to the
   registry when Lean is unavailable or Mathlib is not set up.

Pipeline integration:
  ManimCodeGenerator.generate(concept, mode="lean")
    → LeanProofAnimator.enrich(concept)      # returns LeanStructure | None
    → generate_primitive(concept, lean_hint=structure)  # tighter prompt
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from src.concepts.extractor import Concept

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class LeanField:
    """One structural element of a Lean type (constructor arg or record field)."""
    name: str          # Lean field name, e.g. "eigenvalues"
    lean_type: str     # Type as it appears in Lean, e.g. "ι → ℝ"
    visual_role: str   # What it looks like, e.g. "diagonal values on D matrix"
    beat_param: str    # Which JSON key this maps to in the beat, e.g. "eigenvalues"


@dataclass
class LeanStructure:
    """Enriched information about a Lean / Mathlib type relevant to animation."""
    lean_name: str                      # e.g. "Matrix.IsHermitian"
    display_name: str                   # e.g. "Hermitian matrix eigendecomposition"
    family: str                         # Mathlib family tag
    description: str                    # One-sentence explanation
    fields: list[LeanField]             # Structural components
    primary_beat: str                   # Best beat type from DSL catalog
    beat_hints: str                     # Natural language hints for beat parameterisation
    example_spec_fragment: str = ""     # Optional JSON fragment showing a good beat


# ---------------------------------------------------------------------------
# Mathlib Structure Registry
# ---------------------------------------------------------------------------
# Each entry captures the animation-relevant structure of a Lean 4 / Mathlib type.
# When a concept is matched to an entry, the hints are injected into the codegen
# prompt so the LLM can parameterise beats precisely rather than guessing.

_REGISTRY: list[LeanStructure] = [

    # ── Linear Algebra ──────────────────────────────────────────────────────

    LeanStructure(
        lean_name="Matrix.IsHermitian",
        display_name="Hermitian / Symmetric matrix eigendecomposition",
        family="linear_algebra",
        description="A matrix A is Hermitian if A = Aᴴ. "
                    "It admits an eigendecomposition A = VDVᴴ where D is diagonal real.",
        fields=[
            LeanField("val",         "Matrix n n ℝ",   "the symmetric matrix A",       "matrix"),
            LeanField("eigenvalues", "n → ℝ",          "diagonal of D (real λ values)", "eigenvalues"),
            LeanField("eigenvectorMatrix", "Matrix n n ℝ", "V: columns are eigenvectors", "eigenvectors"),
        ],
        primary_beat="eigendecomposition",
        beat_hints=(
            "Use 'eigendecomposition' beat. "
            "Set matrix to a 2×2 or 3×3 example from the paper. "
            "eigenvalues should be the diagonal entries of D (often sorted descending). "
            "eigenvectors should be the columns of V, normalised to unit length. "
            "title should mention 'Hermitian' or 'Symmetric'."
        ),
        example_spec_fragment=json.dumps({
            "type": "eigendecomposition",
            "matrix": [[2.0, 1.0], [1.0, 2.0]],
            "eigenvalues": [3.0, 1.0],
            "eigenvectors": [[0.707, 0.707], [0.707, -0.707]],
            "labels": ["λ₁=3", "λ₂=1"],
            "title": "Symmetric matrix eigendecomposition",
        }, indent=2),
    ),

    LeanStructure(
        lean_name="Matrix.rank",
        display_name="Matrix rank and SVD",
        family="linear_algebra",
        description="The rank of A equals the number of non-zero singular values in its SVD A = UΣVᵀ.",
        fields=[
            LeanField("val",            "Matrix m n ℝ", "the matrix A",                 "matrix"),
            LeanField("singularValues", "ℕ → ℝ",        "σ₁ ≥ σ₂ ≥ … ≥ 0",             "eigenvalues"),
        ],
        primary_beat="eigendecomposition",
        beat_hints=(
            "Show the matrix as a heatmap alongside its singular values as a bar chart. "
            "Use 'eigendecomposition' beat to show U and V eigenvectors, "
            "or use 'bar_chart' beat with singular values to visualise rank."
        ),
    ),

    LeanStructure(
        lean_name="LinearMap",
        display_name="Linear map / transformation",
        family="linear_algebra",
        description="A linear map T : V → W satisfies T(αu+βv) = αT(u)+βT(v). "
                    "Represented as a matrix via chosen bases.",
        fields=[
            LeanField("toFun",    "V → W",           "the mapping function",         "matrix"),
            LeanField("map_add",  "proof",            "additivity",                   ""),
            LeanField("map_smul", "proof",            "homogeneity",                  ""),
        ],
        primary_beat="side_by_side",
        beat_hints=(
            "Show input vector space on the left, output on the right, "
            "with arrows through the matrix in the middle. "
            "Use 'side_by_side' beat: labels=[\"Input V\", \"Matrix A\", \"Output W\"]. "
            "Then add an 'eigendecomposition' beat showing how the basis is stretched."
        ),
    ),

    LeanStructure(
        lean_name="inner_product_geometry",
        display_name="Inner product / dot product",
        family="linear_algebra",
        description="The inner product ⟨u, v⟩ = uᵀv measures the angle and projection between vectors.",
        fields=[
            LeanField("u",   "EuclideanSpace ℝ n", "first vector",     "from_labels"),
            LeanField("v",   "EuclideanSpace ℝ n", "second vector",    "to_labels"),
            LeanField("dot", "ℝ",                  "scalar result",    "weights"),
        ],
        primary_beat="weighted_connections",
        beat_hints=(
            "Show the two vectors as nodes on top and bottom rows with weighted lines "
            "representing their elementwise products before summing. "
            "Use 'weighted_connections' beat. "
            "Finish with a 'bar_chart' showing the component contributions."
        ),
    ),

    # ── Attention / Transformer ──────────────────────────────────────────────

    LeanStructure(
        lean_name="attention_scaled_dot_product",
        display_name="Scaled dot-product attention",
        family="attention",
        description="Attention(Q,K,V) = softmax(QKᵀ/√d_k)V. "
                    "Queries attend to keys; values are aggregated with learned weights.",
        fields=[
            LeanField("Q",   "Matrix n d_k ℝ", "query matrix",          "query_labels"),
            LeanField("K",   "Matrix m d_k ℝ", "key matrix",            "key_labels"),
            LeanField("V",   "Matrix m d_v ℝ", "value matrix",          ""),
            LeanField("d_k", "ℕ",              "key dimension (scaler)",""),
        ],
        primary_beat="attention_matrix",
        beat_hints=(
            "Use 'attention_matrix' beat. "
            "query_labels are the query token names, key_labels are key token names. "
            "scores[i][j] = softmax(Q[i]·K[j]/√d_k). All values must be in [0,1]. "
            "Set highlight_query to the most interesting query row. "
            "Follow with a 'weighted_connections' beat showing value aggregation."
        ),
        example_spec_fragment=json.dumps({
            "type": "attention_matrix",
            "query_labels": ["the", "cat", "sat"],
            "key_labels":   ["the", "cat", "sat"],
            "scores": [[0.7, 0.2, 0.1], [0.1, 0.6, 0.3], [0.2, 0.3, 0.5]],
            "highlight_query": 1,
            "title": "Self-attention scores",
        }, indent=2),
    ),

    LeanStructure(
        lean_name="multi_head_attention",
        display_name="Multi-head attention",
        family="attention",
        description="Multi-head attention runs h attention functions in parallel, "
                    "concatenating their outputs: MultiHead(Q,K,V) = Concat(head₁,…,headₕ)Wᴼ.",
        fields=[
            LeanField("h",       "ℕ",          "number of heads",                  ""),
            LeanField("W_Q",     "Matrix d_k", "query projection per head",        ""),
            LeanField("W_K",     "Matrix d_k", "key projection per head",          ""),
            LeanField("W_V",     "Matrix d_v", "value projection per head",        ""),
            LeanField("W_O",     "Matrix d_m", "output projection",                ""),
        ],
        primary_beat="node_row",
        beat_hints=(
            "Show h parallel attention heads as a 'node_row', then merge with 'side_by_side'. "
            "Use one 'attention_matrix' beat for a single head to show what each head attends to. "
            "Colors: different head = different color from BLUE_C, GREEN_C, ORANGE, PINK."
        ),
    ),

    LeanStructure(
        lean_name="softmax",
        display_name="Softmax normalisation",
        family="attention",
        description="softmax(z)ᵢ = exp(zᵢ) / Σⱼ exp(zⱼ). Converts logits to a probability distribution.",
        fields=[
            LeanField("z",      "Vector n ℝ", "input logits",            "values"),
            LeanField("output", "Vector n ℝ", "output probabilities summing to 1", "then_transform"),
        ],
        primary_beat="bar_chart",
        beat_hints=(
            "Use 'bar_chart' beat with values=raw logits (normalised to [0,1]), "
            "then_transform=softmax outputs. This animates the normalisation step. "
            "Colors=BLUE_C for logits, and the transform bars turn GREEN_C."
        ),
    ),

    # ── Probability / Statistics ─────────────────────────────────────────────

    LeanStructure(
        lean_name="ProbabilityTheory.Measure",
        display_name="Probability distribution",
        family="probability",
        description="A probability measure μ assigns non-negative mass to measurable sets, "
                    "with total mass 1.",
        fields=[
            LeanField("support",    "Set Ω",  "where mass is concentrated", "hypotheses"),
            LeanField("mass",       "Ω → ℝ≥0", "probability of each event", "prior"),
        ],
        primary_beat="bar_chart",
        beat_hints=(
            "Show the distribution as a 'bar_chart' with labels=support elements "
            "and values=probabilities (must sum to 1). "
            "If the paper shows a Bayesian update, use 'bayes' beat instead."
        ),
    ),

    LeanStructure(
        lean_name="ProbabilityTheory.condexp",
        display_name="Bayesian conditional probability",
        family="probability",
        description="P(H|E) = P(E|H)·P(H) / P(E). Posterior belief after observing evidence.",
        fields=[
            LeanField("prior",      "H → ℝ≥0", "P(H): belief before evidence",  "prior"),
            LeanField("likelihood", "H → ℝ≥0", "P(E|H): how likely evidence is", "likelihood"),
            LeanField("posterior",  "H → ℝ≥0", "P(H|E): updated belief",         ""),
        ],
        primary_beat="bayes",
        beat_hints=(
            "Use 'bayes' beat. prior=[P(H₁),…] (will be auto-normalised), "
            "likelihood=[P(E|H₁),…], hypotheses=[\"H₁\",…]. "
            "The animation automatically transforms blue prior bars into green posterior bars."
        ),
        example_spec_fragment=json.dumps({
            "type": "bayes",
            "hypotheses": ["H₁", "H₂", "H₃"],
            "prior": [0.33, 0.33, 0.34],
            "likelihood": [0.9, 0.4, 0.1],
            "title": "Bayesian update",
        }, indent=2),
    ),

    LeanStructure(
        lean_name="MeasureTheory.integral",
        display_name="Lebesgue / expected value integral",
        family="probability",
        description="E[f(X)] = ∫ f(x) dμ(x). The expectation of f under measure μ.",
        fields=[
            LeanField("f",   "Ω → ℝ", "the function being integrated", ""),
            LeanField("mu",  "Measure", "the probability measure",       ""),
        ],
        primary_beat="bar_chart",
        beat_hints=(
            "Show a 'bar_chart' of f(x) values at discrete sample points, "
            "then animate weights (μ(x)) multiplying the bars to show E[f(X)]. "
            "Use then_transform to animate from f values to f·p values."
        ),
    ),

    # ── Optimisation ────────────────────────────────────────────────────────

    LeanStructure(
        lean_name="gradient_descent_iteration",
        display_name="Gradient descent update rule",
        family="optimization",
        description="θₜ₊₁ = θₜ - η∇L(θₜ). Each step moves parameters in the direction of steepest descent.",
        fields=[
            LeanField("L",   "θ → ℝ",  "loss function",         "fn_type"),
            LeanField("eta", "ℝ",       "learning rate",         "learning_rate"),
            LeanField("n",   "ℕ",       "number of steps",       "n_steps"),
        ],
        primary_beat="gradient_step",
        beat_hints=(
            "Use 'gradient_step' beat. "
            "fn_type='quadratic' for MSE loss (a·x²+b·x+c), 'sine' for non-convex. "
            "learning_rate from the paper (typical: 0.001–0.1 for Adam, 0.01–0.3 for SGD). "
            "n_steps=4–6 to show convergence without crowding."
        ),
        example_spec_fragment=json.dumps({
            "type": "gradient_step",
            "fn_type": "quadratic",
            "a": 1.0, "b": 0.0, "c": 0.0,
            "x_range": [-3.0, 3.0],
            "start_x": 2.5,
            "learning_rate": 0.4,
            "n_steps": 5,
            "title": "Gradient descent on MSE",
        }, indent=2),
    ),

    LeanStructure(
        lean_name="convex_optimization",
        display_name="Convex function minimisation",
        family="optimization",
        description="min f(x) subject to x ∈ C where f is convex. Global minimum guaranteed.",
        fields=[
            LeanField("f",          "E → ℝ",  "convex objective",           "fn_type"),
            LeanField("constraint", "Set E",   "feasible set C",             ""),
            LeanField("minimizer",  "E",       "x* where ∇f(x*)=0",         "start_x"),
        ],
        primary_beat="gradient_step",
        beat_hints=(
            "Use 'gradient_step' beat with fn_type='quadratic' (canonical convex shape). "
            "Place start_x far from the minimum to show convergence. "
            "Precede with a 'text' beat naming the optimisation problem."
        ),
    ),

    # ── Graph Theory ─────────────────────────────────────────────────────────

    LeanStructure(
        lean_name="SimpleGraph",
        display_name="Simple graph (nodes and edges)",
        family="graph",
        description="A simple graph G = (V, E) with vertices V and undirected edges E ⊆ V×V, no self-loops.",
        fields=[
            LeanField("V",    "Type",           "vertex set",                       "nodes"),
            LeanField("Adj",  "V → V → Prop",  "adjacency relation (symmetric)",   "edges"),
        ],
        primary_beat="tree",
        beat_hints=(
            "Use 'tree' beat for trees/DAGs, or 'node_row' + 'weighted_connections' for bipartite graphs. "
            "nodes=list of vertex labels, edges=[[u,v],...] (0-indexed). "
            "If the paper shows an algorithm (BFS/DFS), set traversal_order."
        ),
    ),

    LeanStructure(
        lean_name="Quiver",
        display_name="Directed graph / DAG",
        family="graph",
        description="A quiver (directed multigraph) V with morphisms between vertices. "
                    "Used for computation graphs, neural network dataflow.",
        fields=[
            LeanField("V",   "Type",          "vertex type",           "nodes"),
            LeanField("Hom", "V → V → Type", "directed edge type",    "edges"),
        ],
        primary_beat="flow_column",
        beat_hints=(
            "For DAG computation graphs (e.g. forward pass), use 'flow_column' for sequential, "
            "or 'tree' for branching structure. "
            "For neural net layers, use 'node_row' at each depth level."
        ),
    ),

    LeanStructure(
        lean_name="BFS_algorithm",
        display_name="Breadth-first search",
        family="graph",
        description="BFS explores a graph level by level from a source node, "
                    "discovering all vertices reachable within k hops before k+1.",
        fields=[
            LeanField("G",     "SimpleGraph V", "input graph",             "nodes/edges"),
            LeanField("src",   "V",             "source vertex",           "traversal_order[0]"),
            LeanField("queue", "List V",        "frontier nodes",          ""),
        ],
        primary_beat="tree",
        beat_hints=(
            "Use 'tree' beat. Set traversal_order to the BFS visit sequence (0-indexed). "
            "node_color='BLUE', highlight_color='YELLOW'. "
            "Title: 'BFS from node 0'."
        ),
    ),

    # ── Neural Networks ──────────────────────────────────────────────────────

    LeanStructure(
        lean_name="feedforward_network",
        display_name="Feedforward neural network",
        family="neural_network",
        description="A composition of affine layers and non-linearities: "
                    "f(x) = σ(W_n·…·σ(W₁x+b₁)…+bₙ).",
        fields=[
            LeanField("layers",      "List (Matrix ℝ)",     "weight matrices",         "labels"),
            LeanField("activations", "List (ℝ → ℝ)",        "activation functions",    ""),
            LeanField("depth",       "ℕ",                    "number of layers",        ""),
        ],
        primary_beat="flow_column",
        beat_hints=(
            "Use 'flow_column' beat with labels=['Input', 'Hidden 1', 'Hidden 2', 'Output']. "
            "highlight the layer being discussed. "
            "Follow with 'node_row' to show activations at one layer."
        ),
    ),

    LeanStructure(
        lean_name="batch_normalisation",
        display_name="Batch normalisation",
        family="neural_network",
        description="BN(x) = γ·(x-μ_B)/√(σ²_B+ε) + β. Normalises activations over a mini-batch.",
        fields=[
            LeanField("x",      "Batch → ℝⁿ", "input activations",       "values"),
            LeanField("mu_B",   "ℝⁿ",          "batch mean",              ""),
            LeanField("sigma_B","ℝⁿ",           "batch standard deviation",""),
            LeanField("gamma",  "ℝⁿ",           "learned scale",          ""),
            LeanField("beta",   "ℝⁿ",           "learned shift",          ""),
        ],
        primary_beat="bar_chart",
        beat_hints=(
            "Use 'bar_chart' beat: values=raw activations (normalised to [0,1]), "
            "then_transform=after BatchNorm values. "
            "Title='Batch normalisation effect'."
        ),
    ),

    # ── Sequences / Recurrences ───────────────────────────────────────────────

    LeanStructure(
        lean_name="recurrence_relation",
        display_name="Recurrence / dynamic programming",
        family="algorithm",
        description="A recurrence f(n) = g(f(n-1), f(n-2), …) defines a sequence or DP table.",
        fields=[
            LeanField("base", "f 0 = …",         "base case(s)",           ""),
            LeanField("step", "f n = g(f (n-1))", "recurrence step",        ""),
        ],
        primary_beat="bar_chart",
        beat_hints=(
            "Show the first 5-7 computed values as a 'bar_chart', "
            "with then_transform showing a later step in the recurrence. "
            "Or use 'tree' beat to show the call tree."
        ),
    ),

    LeanStructure(
        lean_name="Filter.Tendsto",
        display_name="Sequence convergence / limit",
        family="sequence",
        description="aₙ → L means ∀ε>0, ∃N, n≥N → |aₙ-L| < ε.",
        fields=[
            LeanField("f",      "ℕ → ℝ",  "sequence terms",             "values"),
            LeanField("atTop",  "Filter",  "the n→∞ filter",             ""),
            LeanField("limit",  "ℝ",       "the limit L",                ""),
        ],
        primary_beat="bar_chart",
        beat_hints=(
            "Use 'bar_chart' beat with values=[a₁,a₂,…,a₇] (first 7 terms). "
            "then_transform=[a₈,…] (later terms closer to L). "
            "Add a 'text' beat first to state the limit value L."
        ),
    ),

    # ── Calculus ────────────────────────────────────────────────────────────

    LeanStructure(
        lean_name="HasDerivAt",
        display_name="Derivative / gradient",
        family="calculus",
        description="f has derivative f'(x₀) at x₀: the slope of the tangent line.",
        fields=[
            LeanField("f",   "ℝ → ℝ",  "the function",        "fn_type"),
            LeanField("f'",  "ℝ",       "derivative value",    "a"),
            LeanField("x₀",  "ℝ",       "the point",           "start_x"),
        ],
        primary_beat="gradient_step",
        beat_hints=(
            "Use 'gradient_step' beat with n_steps=1 to show one tangent arrow at x₀. "
            "learning_rate near 0 to keep the dot from moving far. "
            "fn_type matches the function shape ('quadratic', 'sine', etc.)."
        ),
    ),

    LeanStructure(
        lean_name="intervalIntegral",
        display_name="Definite integral / area under curve",
        family="calculus",
        description="∫ₐᵇ f(x)dx = signed area between f and the x-axis on [a,b].",
        fields=[
            LeanField("f",  "ℝ → ℝ", "integrand",       "fn_type"),
            LeanField("a",  "ℝ",      "lower bound",      "x_range[0]"),
            LeanField("b",  "ℝ",      "upper bound",      "x_range[1]"),
        ],
        primary_beat="gradient_step",
        beat_hints=(
            "Use 'gradient_step' beat to show the function curve, then annotate the area. "
            "Alternatively, 'bar_chart' can approximate the integral as a Riemann sum: "
            "values=[f(x₁),…,f(xₙ)] for n sample points in [a,b]."
        ),
    ),
]

# Build lookup indices
_BY_LEAN_NAME: dict[str, LeanStructure] = {s.lean_name: s for s in _REGISTRY}
_BY_FAMILY: dict[str, list[LeanStructure]] = {}
for _s in _REGISTRY:
    _BY_FAMILY.setdefault(_s.family, []).append(_s)


# ---------------------------------------------------------------------------
# Structure matching
# ---------------------------------------------------------------------------

def match_lean_structure(concept: "Concept") -> Optional[LeanStructure]:
    """Find the best Mathlib structure for a concept.

    Uses keyword overlap between the concept text and each structure's
    lean_name, display_name, and description. Falls back to None if no
    good match is found (caller should use primitive mode without hints).
    """
    text = f"{concept.name} {concept.description}".lower()
    text = re.sub(r"[-_/]", " ", text)

    best: Optional[LeanStructure] = None
    best_score = 0

    for struct in _REGISTRY:
        # Score: keyword matches in the structure's text
        struct_text = f"{struct.lean_name} {struct.display_name} {struct.description}".lower()
        struct_text = re.sub(r"[-_/.]", " ", struct_text)
        keywords = set(struct_text.split())
        score = sum(1 for kw in keywords if kw in text and len(kw) > 3)
        if score > best_score:
            best_score = score
            best = struct

    # Require at least 2 keyword matches to avoid spurious hits
    return best if best_score >= 2 else None


def get_structures_for_family(family: str) -> list[LeanStructure]:
    """Return all registry entries for a given Mathlib family."""
    return _BY_FAMILY.get(family, [])


def get_structure_by_name(lean_name: str) -> Optional[LeanStructure]:
    """Return a structure by its exact Lean name."""
    return _BY_LEAN_NAME.get(lean_name)


# ---------------------------------------------------------------------------
# LeanClient — subprocess wrapper
# ---------------------------------------------------------------------------

class LeanClient:
    """
    Thin wrapper around the `lean --stdin` subprocess.

    Works without Mathlib for core Lean 4 expressions. For Mathlib queries,
    set LEAN_PROJECT_PATH to a directory containing a configured lake project
    with Mathlib as a dependency (lake build already completed).

    All methods return None and log a warning on failure — callers should
    treat None as "no information available" and proceed with the registry.
    """

    def __init__(self):
        self._lean_bin = self._find_lean()
        self._lake_project = os.environ.get("LEAN_PROJECT_PATH", "")

    @staticmethod
    def _find_lean() -> Optional[str]:
        import shutil
        # Check common elan location first
        elan_lean = os.path.expanduser("~/.elan/bin/lean")
        if os.path.isfile(elan_lean):
            return elan_lean
        return shutil.which("lean")

    @property
    def available(self) -> bool:
        return self._lean_bin is not None

    @property
    def mathlib_available(self) -> bool:
        """True if a configured Lake+Mathlib project is available."""
        if not self._lake_project:
            return False
        project = Path(self._lake_project)
        return (project / "lakefile.lean").exists() or (project / "lakefile.toml").exists()

    def check_type(self, lean_expr: str, imports: list[str] | None = None) -> Optional[str]:
        """Run `#check lean_expr` and return the type string, or None on failure.

        Args:
            lean_expr: A core Lean 4 expression, e.g. "Nat.succ 3"
            imports: Optional list of Lean import paths (e.g. ["Mathlib.Data.Real.Basic"])
                     Only works if mathlib_available is True.
        """
        if not self.available:
            return None

        import_block = ""
        if imports and self.mathlib_available:
            import_block = "\n".join(f"import {imp}" for imp in imports) + "\n\n"

        code = f"{import_block}#check {lean_expr}"
        return self._run_lean(code)

    def eval_expr(self, lean_expr: str) -> Optional[str]:
        """Run `#eval lean_expr` and return the output string."""
        if not self.available:
            return None
        return self._run_lean(f"#eval {lean_expr}")

    def _run_lean(self, code: str, timeout: int = 15) -> Optional[str]:
        """Run Lean code via stdin and return stdout, or None on error."""
        if not self.available:
            return None
        try:
            env = os.environ.copy()
            if self.mathlib_available:
                env["LEAN_PATH"] = str(Path(self._lake_project) / ".lake" / "build" / "lib")

            result = subprocess.run(
                [self._lean_bin, "--stdin"],
                input=code.encode(),
                capture_output=True,
                timeout=timeout,
                env=env,
            )
            out = result.stdout.decode(errors="replace").strip()
            err = result.stderr.decode(errors="replace").strip()
            if out:
                return out
            # lean --stdin writes type info to stderr for #check
            if err and "error" not in err.lower():
                return err
            return None
        except subprocess.TimeoutExpired:
            _log.warning("lean --stdin timed out for code: %s", code[:80])
            return None
        except Exception as exc:
            _log.warning("lean --stdin failed: %s", exc)
            return None

    def check_definition_exists(self, lean_name: str) -> bool:
        """Return True if lean_name is a valid identifier in Lean's environment."""
        result = self.check_type(lean_name)
        return result is not None and "error" not in result.lower()


# ---------------------------------------------------------------------------
# LeanProofAnimator — main integration point
# ---------------------------------------------------------------------------

class LeanProofAnimator:
    """
    Enriches paper2vis concepts with Mathlib structure information.

    The animator matches each concept against the structure registry,
    optionally verifies the match with a live Lean query, and returns
    enrichment data (beat hints, example spec fragment) that the codegen
    prompt can use to produce better-parameterised AnimationSpec objects.
    """

    def __init__(self):
        self._client = LeanClient()
        if self._client.available:
            _log.info("LeanClient initialised (lean at %s)", self._client._lean_bin)
            if self._client.mathlib_available:
                _log.info("Mathlib project at %s", self._client._lake_project)
        else:
            _log.info("LeanClient unavailable — using registry only")

    def enrich(self, concept: "Concept") -> Optional[LeanStructure]:
        """Match concept → LeanStructure, optionally verify with Lean subprocess.

        Returns None if no registry match is found.
        """
        structure = match_lean_structure(concept)
        if structure is None:
            return None

        # Optional: verify the lean_name actually exists in Lean
        if self._client.available and not structure.lean_name.startswith("attention_") \
                and not structure.lean_name.endswith("_algorithm") \
                and not "_" in structure.lean_name[:3]:
            # Only verify names that look like real Lean identifiers (not our internal keys)
            lean_id = structure.lean_name
            if self._client.check_definition_exists(lean_id):
                _log.info("Lean verified: %s exists", lean_id)
            else:
                _log.debug("Lean could not verify %s (may need Mathlib)", lean_id)

        return structure

    def build_prompt_hint(self, structure: LeanStructure) -> str:
        """Return a formatted hint block for injection into the primitive codegen prompt."""
        lines = [
            f"## Lean/Mathlib structure: `{structure.lean_name}`",
            f"**{structure.display_name}**",
            f"{structure.description}",
            "",
            "### Structural fields",
        ]
        for f in structure.fields:
            if f.visual_role:
                lines.append(f"- `{f.name} : {f.lean_type}` — {f.visual_role}")
        lines += [
            "",
            f"### Beat guidance",
            f"Recommended beat: **{structure.primary_beat}**",
            structure.beat_hints,
        ]
        if structure.example_spec_fragment:
            lines += [
                "",
                "### Example beat JSON",
                f"```json\n{structure.example_spec_fragment}\n```",
            ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Convenience singleton
# ---------------------------------------------------------------------------

_animator: Optional[LeanProofAnimator] = None


def get_animator() -> LeanProofAnimator:
    global _animator
    if _animator is None:
        _animator = LeanProofAnimator()
    return _animator
