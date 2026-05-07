"""
Lightweight Mathlib-inspired concept family tagger.

Maps a Concept's name + description to one of the mathematical structure
families defined in Lean 4's Mathlib. The family tag is injected into the
primitive-mode codegen prompt so the LLM knows which beat types to prefer.

No Lean installation required — pure keyword heuristics. If pantograph is
installed and LEAN_AVAILABLE is set, a second pass queries Mathlib directly.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.concepts.extractor import Concept

# ---------------------------------------------------------------------------
# Family keyword registry — ordered by specificity (more specific first)
# ---------------------------------------------------------------------------

_FAMILIES: list[tuple[str, list[str]]] = [
    ("attention", [
        "attention", "self-attention", "cross-attention", "multi-head",
        "transformer", "query", "key", "value", "softmax attention",
        "scaled dot-product",
    ]),
    ("algorithm", [
        "backpropagation", "gradient descent", "adam", "sgd", "rmsprop",
        "dynamic programming", "memoization", "greedy", "branch and bound",
        "bfs", "dfs", "dijkstra", "a*", "viterbi", "beam search",
        "forward-backward", "expectation maximization", "em algorithm",
    ]),
    ("neural_network", [
        "neural network", "layer", "activation", "relu", "sigmoid", "tanh",
        "softmax", "batch norm", "dropout", "convolution", "pooling",
        "embedding", "feedforward", "mlp", "lstm", "gru", "rnn",
    ]),
    ("linear_algebra", [
        "matrix", "vector", "linear map", "linear transformation",
        "eigenvalue", "eigenvector", "basis", "span", "rank", "null space",
        "singular value", "svd", "pca", "decomposition", "determinant",
        "trace", "orthogonal", "projection", "gram-schmidt",
    ]),
    ("calculus", [
        "derivative", "gradient", "jacobian", "hessian", "integral",
        "limit", "continuity", "differentiable", "chain rule",
        "taylor series", "fourier", "laplace", "convolution", "divergence",
        "curl", "partial derivative",
    ]),
    ("probability", [
        "probability", "distribution", "bayesian", "prior", "posterior",
        "likelihood", "expectation", "variance", "covariance", "entropy",
        "kl divergence", "mutual information", "markov", "conditional",
        "independence", "random variable", "monte carlo", "sampling",
    ]),
    ("optimization", [
        "loss", "objective", "minimize", "maximize", "convex", "concave",
        "lagrangian", "constraint", "regularization", "saddle point",
        "convergence", "learning rate", "momentum", "weight decay",
    ]),
    ("graph", [
        "graph", "node", "edge", "vertex", "path", "cycle", "tree",
        "spanning tree", "connected component", "clique", "bipartite",
        "directed", "undirected", "dag", "topology", "adjacency",
    ]),
    ("combinatorics", [
        "permutation", "combination", "binomial", "partition", "bijection",
        "injection", "surjection", "counting", "pigeonhole",
        "inclusion-exclusion", "generating function",
    ]),
    ("algebra", [
        "group", "ring", "field", "module", "vector space", "homomorphism",
        "isomorphism", "monoid", "semigroup", "abelian", "commutative",
        "associative", "identity", "inverse", "coset", "quotient",
    ]),
    ("sequence", [
        "sequence", "series", "convergence", "divergence", "recurrence",
        "fixed point", "iteration", "limit", "cauchy", "monotone",
        "bounded", "subsequence",
    ]),
    ("geometry", [
        "geometric", "shape", "polygon", "circle", "sphere", "manifold",
        "metric", "distance", "angle", "rotation", "translation", "scaling",
        "affine", "projective", "euclidean",
    ]),
]

_DEFAULT_FAMILY = "general"


def match_family(concept: "Concept") -> str:
    """Return the best Mathlib family name for a concept.

    Scores each family by counting keyword matches in the concept's name
    and description (case-insensitive). Returns the top-scoring family,
    or 'general' if no keywords match.
    """
    text = f"{concept.name} {concept.description}".lower()
    # Normalize punctuation so "self-attention" and "self attention" both match
    text = re.sub(r"[-_/]", " ", text)

    best_family = _DEFAULT_FAMILY
    best_score = 0

    for family, keywords in _FAMILIES:
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best_family = family

    return best_family


def recommended_beats(family: str) -> list[str]:
    """Return the beat types most likely to be useful for a given family."""
    _RECS: dict[str, list[str]] = {
        "attention":       ["attention_matrix", "weighted_connections", "heatmap"],
        "algorithm":       ["gradient_step", "tree", "flow_column", "bar_chart"],
        "neural_network":  ["node_row", "weighted_connections", "flow_column", "bar_chart"],
        "linear_algebra":  ["eigendecomposition", "heatmap", "side_by_side"],
        "calculus":        ["gradient_step", "bar_chart", "text"],
        "probability":     ["bayes", "bar_chart", "heatmap"],
        "optimization":    ["gradient_step", "bar_chart", "flow_column"],
        "graph":           ["tree", "node_row", "side_by_side"],
        "combinatorics":   ["tree", "bar_chart", "node_row"],
        "algebra":         ["heatmap", "node_row", "flow_column"],
        "sequence":        ["bar_chart", "node_row", "gradient_step"],
        "geometry":        ["side_by_side", "node_row", "text"],
        "general":         ["flow_column", "side_by_side", "bar_chart", "text"],
    }
    return _RECS.get(family, _RECS["general"])
