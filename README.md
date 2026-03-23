# paper2vis

**paper2vis** turns academic papers (PDF) into animated visualizations using LLMs and [Manim](https://www.manim.community/).

It parses a PDF, extracts key concepts using an LLM, generates Manim scene code for each concept, and renders them into `.mp4` files.

---

## How It Works

```
PDF → [parse] → sections/equations → [LLM extract] → Concepts → [LLM codegen] → Manim code → [render] → .mp4
```

1. **Parser** — PyMuPDF extracts text, sections, equations, and figure captions
2. **Concept Extractor** — LLM reads each section and identifies visualizable concepts
3. **Code Generator** — LLM writes a complete Manim scene for each concept
4. **Renderer** — Manim renders each scene to video

---

## Setup

### Prerequisites

- Python 3.10+
- [Manim](https://docs.manim.community/en/stable/installation.html) and its system deps (LaTeX, ffmpeg, cairo)
- An Anthropic or OpenAI API key

### Install

```bash
git clone <repo>
cd paper2vis
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# Edit .env and add your API key
```

---

## Usage

### CLI

```bash
# Run the full pipeline on a paper
python -m src.pipeline papers/mypaper.pdf

# Specify output directory
python -m src.pipeline papers/mypaper.pdf --output output/myrun

# Use OpenAI instead of Anthropic
python -m src.pipeline papers/mypaper.pdf --provider openai --model gpt-4o
```

### Python API

```python
from src.pipeline import Pipeline

pipeline = Pipeline(provider="anthropic", model="claude-opus-4-5")
results = pipeline.run("papers/attention_is_all_you_need.pdf")

for concept, video_path in results:
    print(f"{concept.name} → {video_path}")
```

---

## Output Structure

```
output/
└── myrun_2024-01-15_143022/
    ├── concepts.json          # extracted concepts
    ├── manim/
    │   ├── concept_0_attention.py
    │   └── concept_1_softmax.py
    └── videos/
        ├── concept_0_attention.mp4
        └── concept_1_softmax.mp4
```

---

## Project Layout

```
src/
├── pipeline.py        # main orchestration
├── parser/            # PDF text extraction
├── concepts/          # LLM concept extraction
├── animation/         # code generation + Manim rendering
└── templates/         # reusable Manim scene base classes
prompts/               # LLM prompt templates
papers/                # drop PDFs here
output/                # rendered videos land here
tests/                 # test suite
```

---

## Configuration

| Env var | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `LLM_PROVIDER` | `anthropic` | Which LLM provider to use |
| `LLM_MODEL` | `claude-opus-4-5` | Model name |

---

## Notes

- Manim requires LaTeX for equation rendering. Install a TeX distribution (e.g., MiKTeX, TeX Live).
- Complex papers may produce many concepts; use `--max-concepts N` to limit.
- Generated Manim code may occasionally need manual tweaks for very unusual math notation.
