#!/usr/bin/env python3
"""
Fetch 3Blue1Brown video code from GitHub, adapt it to Manim Community v0.18+,
and index the best scenes into the paper2vis RAG store.

Usage:
    python scripts/index_3b1b.py [--dry-run] [--clear]

Options:
    --dry-run   Print extracted examples without saving
    --clear     Remove existing 3b1b entries before re-indexing
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

# Make src importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.animation.rag import ExampleStore, ManimExample, _EXAMPLES_PATH
from src.llm_utils import call_llm

# ---------------------------------------------------------------------------
# Target files — cherry-picked for mathematical richness
# ---------------------------------------------------------------------------

RAW_BASE = "https://raw.githubusercontent.com/3b1b/videos/master"

TARGETS = [
    {
        "path": "_2017/nn/part1.py",
        "field": "machine_learning",
        "topic": "neural network layers, activations, and matrix multiplication",
        "tags": ["neural_network", "sigmoid", "activation", "layers", "weights", "matrix"],
    },
    {
        "path": "_2017/nn/part3.py",
        "field": "machine_learning",
        "topic": "backpropagation and gradient flow through a neural network",
        "tags": ["backpropagation", "gradient", "chain_rule", "derivative", "neural_network"],
    },
    {
        "path": "_2018/fourier.py",
        "field": "signal_processing",
        "topic": "Fourier transform, frequency decomposition, and winding numbers",
        "tags": ["fourier", "frequency", "sine", "transform", "winding", "complex", "spectrum"],
    },
    {
        "path": "_2019/bayes/part1.py",
        "field": "probability",
        "topic": "Bayes theorem with area diagrams and probability updating",
        "tags": ["bayes", "probability", "conditional", "prior", "posterior", "update"],
    },
    {
        "path": "_2019/diffyq/part2/staging.py",
        "field": "calculus",
        "topic": "differential equations, phase portraits, and vector fields",
        "tags": ["differential_equation", "phase_portrait", "vector_field", "flow", "ode"],
    },
    {
        "path": "_2022/wordle.py",
        "field": "probability",
        "topic": "information theory, entropy, and expected value calculations",
        "tags": ["entropy", "information", "expected_value", "probability", "distribution"],
    },
    {
        "path": "_2023/clt/main.py",
        "field": "probability",
        "topic": "central limit theorem, sums of random variables, Gaussian emergence",
        "tags": ["central_limit_theorem", "gaussian", "normal_distribution", "sum", "variance"],
    },
    {
        "path": "_2016/eola/chapter3.py",
        "field": "linear_algebra",
        "topic": "linear transformations as matrix multiplication on vectors",
        "tags": ["linear_transform", "matrix", "vector", "basis", "eigenvector", "determinant"],
    },
    {
        "path": "_2018/div_curl.py",
        "field": "calculus",
        "topic": "divergence and curl of vector fields",
        "tags": ["divergence", "curl", "vector_field", "gradient", "calculus", "flow"],
    },
    {
        "path": "_2022/piano_fourier.py",
        "field": "signal_processing",
        "topic": "Fourier decomposition applied to piano notes and sound waves",
        "tags": ["fourier", "frequency", "sound", "sine_wave", "decomposition", "spectrum"],
    },
]

# ---------------------------------------------------------------------------
# manimlib → Manim Community syntax adaptation rules (regex)
# Applied before sending to LLM — catches the most mechanical differences
# ---------------------------------------------------------------------------

_SYNTAX_RULES: list[tuple[str, str]] = [
    (r"\bTexMobject\b",        "MathTex"),
    (r"\bTextMobject\b",       "Text"),
    (r"\bShowCreation\b",      "Create"),
    (r"\bGrowArrow\b",         "Create"),
    (r"\bFadeInFromDown\b",    "FadeIn"),
    (r"\bFadeOutAndShift\b",   "FadeOut"),
    (r"\bApplyMethod\b",       "Transform"),
    (r"\bSmallDot\b",          "Dot"),
    (r"\bLABEL_SCALE\b",       "0.7"),
    (r"\bSMALL_BUFF\b",        "0.1"),
    (r"\bMED_SMALL_BUFF\b",    "0.2"),
    (r"\bMED_LARGE_BUFF\b",    "0.5"),
    (r"\bLARGE_BUFF\b",        "0.75"),
    # Color renames
    (r"\bLIGHT_GREY\b",        "GREY_B"),
    (r"\bLIGHT_GRAY\b",        "GREY_B"),
    (r"\bDARK_GREY\b",         "GREY_D"),
    (r"\bDARK_GRAY\b",         "GREY_D"),
    (r"\bLIGHT_BROWN\b",       "GOLD_D"),
    (r"\bDARK_BROWN\b",        "GOLD_E"),
]


def _pre_adapt(code: str) -> str:
    for pattern, replacement in _SYNTAX_RULES:
        code = re.sub(pattern, replacement, code)
    return code


# ---------------------------------------------------------------------------
# Scene extraction — pull class bodies from raw Python source
# ---------------------------------------------------------------------------

def extract_scene_classes(source: str) -> list[dict]:
    """
    Extract top-level Scene subclasses from a manimlib source file.
    Returns list of {"name": str, "body": str} dicts.
    Skips PiCreature-heavy scenes.
    """
    SKIP_BASES = {
        "PiCreatureScene", "TeacherStudentsScene", "MortyPiCreatureScene",
        "PiCreatureBubbleScene", "InteractiveScene",
    }
    SKIP_NAMES = re.compile(
        r"(Pi|Morty|Teacher|Student|Bubble|Intro|End|Opening|Closing|Thanks|Credit)",
        re.IGNORECASE,
    )
    # Custom 3b1b helpers that have no Manim Community equivalent
    SKIP_IF_CONTAINS = re.compile(
        r"(get_organized_images|PixelsAsSquares|layer_to_image_array"
        r"|NetworkMobject|get_network|play_creation"
        r"|file_name=\"(?!axes)[^\"]+\"|SVGMobject\(file"
        r"|DISPLAY_CONFIG|FullScreenFadeRectangle)",
    )

    classes = []
    # Match class Foo(Bar): ... up to the next top-level class or EOF
    pattern = re.compile(
        r"^class\s+(\w+)\s*\(([^)]*)\)\s*:",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(source))

    for i, m in enumerate(matches):
        name = m.group(1)
        bases = m.group(2)

        # Skip non-scene or character-heavy classes
        if any(b.strip() in SKIP_BASES for b in bases.split(",")):
            continue
        if SKIP_NAMES.search(name):
            continue
        if "Scene" not in bases and "Animation" not in bases:
            continue

        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(source)
        body = source[start:end].strip()

        # Must have a construct method
        if "def construct(self)" not in body:
            continue
        # Skip trivially short scenes
        if len(body) < 200:
            continue
        # Skip scenes relying on 3b1b-only utilities
        if SKIP_IF_CONTAINS.search(body):
            continue

        classes.append({"name": name, "body": _pre_adapt(body)})

    return classes


# ---------------------------------------------------------------------------
# LLM adaptation prompt
# ---------------------------------------------------------------------------

_ADAPT_PROMPT = """\
You are adapting 3Blue1Brown Manim scenes to Manim Community v0.18+.

The code below has already had mechanical renames applied (TexMobject→MathTex etc.).
Your job: select the 2 most visually interesting scenes and produce clean, runnable
Manim Community code from them.

SELECT scenes that:
- Use ValueTracker, always_redraw, or Axes — continuous animated motion is ideal
- Show a mathematical operation with MathTex formulas changing or equations being derived
- Don't rely on external files, SVG assets, or undefined helper functions
- Are at least 30 lines of construct body

SKIP scenes that reference: get_organized_images, PixelsAsSquares, SVGMobject with file paths,
ImageMobject, NetworkMobject, DISPLAY_CONFIG, PiCreature, play_creation, or any function
not defined in the scene body and not part of standard Manim Community.

ADAPTATION RULES:
- Remove ALL imports — the scene classes only (no `from manim import *`)
- `always_redraw(lambda: ...)` and `ValueTracker` work identically — keep them
- `UpdateFromFunc(obj, func)` → `obj.add_updater(lambda m: func(m))`
- ContinualAnimation subclasses → rewrite as updater pattern
- Remove any `self.embed()`, `self.wait_until_bookmark()` calls
- Replace `self.get_pi_creature()` references with a plain dot or text
- `NumberLine` kwarg `unit_size` → `x_range` with appropriate step
- `Axes` kwarg changes: remove `label_direction`, use `axis_config`
- Keep all mathematical content and ValueTracker animations — they are the gold
- Add `CONTENT_CENTER = DOWN * 0.5` at top of construct if not present and use it
- Ensure title `Text("...", font_size=34).to_edge(UP)` persists throughout

TOPIC: {topic}
FIELD: {field}

SCENES TO ADAPT:
```python
{scenes}
```

Return a JSON array (no markdown fences around the array itself):
[
  {{
    "description": "one precise sentence: what operation is shown, with concrete math terms",
    "tags": ["tag1", "tag2", "tag3"],
    "code": "class SceneName(Scene):\\n    def construct(self):\\n        ..."
  }}
]

Return ONLY the JSON array. No commentary.
"""


def adapt_with_llm(scenes: list[dict], target: dict, provider: str, model: str) -> list[dict]:
    """Call LLM to adapt and curate scenes. Returns list of {description, tags, code}."""
    scenes_text = "\n\n".join(s["body"] for s in scenes[:4])  # cap to avoid token overflow
    prompt = _ADAPT_PROMPT.format(
        topic=target["topic"],
        field=target["field"],
        scenes=scenes_text[:12000],  # hard cap ~12k chars
    )
    raw = call_llm(provider, model, prompt, max_tokens=4096)

    # Extract JSON array
    arr_match = re.search(r"\[\s*\{.*?\}\s*\]", raw, re.DOTALL)
    if not arr_match:
        print(f"    [warn] no JSON array in LLM response for {target['path']}")
        return []
    try:
        return json.loads(arr_match.group(0))
    except json.JSONDecodeError as exc:
        print(f"    [warn] JSON parse failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Index 3b1b scenes into the RAG store")
    parser.add_argument("--dry-run", action="store_true", help="Print without saving")
    parser.add_argument("--clear", action="store_true", help="Remove existing 3b1b entries first")
    parser.add_argument("--provider", default="anthropic", help="LLM provider")
    parser.add_argument("--model", default="claude-sonnet-4-6", help="LLM model")
    parser.add_argument("--targets", nargs="*", help="Subset of target paths to process (substring match)")
    args = parser.parse_args()

    store = ExampleStore(_EXAMPLES_PATH)
    store._ensure_loaded()

    if args.clear:
        before = len(store._examples)
        store._examples = [e for e in store._examples if "3b1b" not in e.source_url]
        store._build_idf()
        print(f"Cleared {before - len(store._examples)} existing 3b1b entries")

    targets = TARGETS
    if args.targets:
        targets = [t for t in TARGETS if any(s in t["path"] for s in args.targets)]
        print(f"Processing {len(targets)} matched targets")

    total_added = 0

    for target in targets:
        url = f"{RAW_BASE}/{target['path']}"
        print(f"\n→ {target['path']}")

        # Fetch
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                source = resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            print(f"  [skip] fetch failed: {exc}")
            continue

        # Extract scene classes
        scenes = extract_scene_classes(source)
        print(f"  {len(scenes)} scenes extracted", end="")
        if not scenes:
            print(" — skipping")
            continue
        print()

        # LLM adaptation
        print(f"  Adapting with {args.provider}/{args.model}…")
        try:
            adapted = adapt_with_llm(scenes, target, args.provider, args.model)
        except Exception as exc:
            print(f"  [skip] LLM failed: {exc}")
            continue

        if not adapted:
            print("  No usable scenes returned")
            continue

        source_url = f"https://github.com/3b1b/videos/blob/master/{target['path']}"

        for item in adapted:
            code = item.get("code", "").strip()
            desc = item.get("description", "").strip()
            tags = list(target["tags"]) + [t for t in item.get("tags", []) if t not in target["tags"]]

            if not code or not desc:
                continue

            example = ManimExample(
                field=target["field"],
                description=desc,
                tags=tags,
                code=code,
                source_url=source_url,
            )

            if args.dry_run:
                print(f"\n  [DRY RUN] {desc}")
                print(f"  tags: {tags}")
                print(f"  code ({len(code)} chars):\n{code[:400]}…")
            else:
                store.add_example(example)
                print(f"  + {desc[:80]}")
                total_added += 1

        # Be polite to GitHub
        time.sleep(1.0)

    if not args.dry_run and total_added > 0:
        store._build_idf()
        store.save()
        print(f"\nSaved {total_added} new examples to {_EXAMPLES_PATH}")
        print(f"RAG store now has {len(store)} total examples")
    elif args.dry_run:
        print(f"\n[dry run complete — {total_added} examples would have been added]")
    else:
        print("\nNo new examples added")


if __name__ == "__main__":
    main()
