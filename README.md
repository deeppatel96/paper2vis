# paper2vis

Turn academic papers (PDF) into narrated Manim animations using LLMs.

```
PDF → parse → concepts → storyboard → Manim code → render → critic → voice → .mp4
```

---

## Quick Start

### Prerequisites

- **Python 3.10+** via [miniforge](https://github.com/conda-forge/miniforge) (or any env manager)
- **Node.js 18+** via [nvm](https://github.com/nvm-sh/nvm)
- **Manim Community v0.18+** and its system deps: `ffmpeg`, `cairo`, `pango`
- **OpenAI API key** (GPT-4o for extraction/codegen, TTS for narration)

> No LaTeX required — the system uses `Text()` + Unicode throughout.

### Install

```bash
git clone <repo> && cd paper2vis

# Python deps
~/miniforge3/bin/pip install -r requirements.txt

# Node deps
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh"
cd web && npm install && cd ..
```

### Configure

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Concept extraction
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o

# Code generation
CODEGEN_PROVIDER=openai
CODEGEN_MODEL=gpt-4o

OPENAI_API_KEY=sk-...
```

---

## Running

### Both servers (recommended)

```bash
make dev
```

This starts the FastAPI backend on `:8000` and the Next.js UI on `:3000`. Open [http://localhost:3000](http://localhost:3000).

### Backend only

```bash
make api
# or directly:
~/miniforge3/bin/uvicorn src.api.main:app --port 8000 --reload --reload-dir src
```

### Frontend only

```bash
make web
# or directly:
cd web && npm run dev
```

---

## How It Works

1. **PDF Parse** — PyMuPDF extracts text sections; optional figure extraction for visual grounding
2. **Concept Extraction** — GPT-4o reads each section and identifies visualizable concepts with shot lists
3. **Code Generation** — Three modes available (select in UI):
   - **Two-pass** (default): storyboard → Manim code. Best quality.
   - **DSL**: concept → typed JSON spec → compiled Manim. Most reliable (no free-form Python).
   - **Direct**: concept → Manim code in one shot. Fastest.
   - **Compare all**: runs all three, renders each, picks best for critic/narration.
4. **RAG injection** — TF-IDF retrieval over 24 curated Manim examples (by scientific field) injected into prompts
5. **Validation** — LLM pre-render checker catches banned APIs, invalid colors, LaTeX usage before Manim runs
6. **Render** — Manim renders the scene; up to 6 retry attempts with LLM error-fixing
7. **Critic loop** — GPT-4o watches the rendered video and proposes targeted fixes (up to 2 passes)
8. **Narration** — OpenAI TTS generates voiceover + WebVTT subtitles synced to video duration

---

## Project Layout

```
src/
├── api/
│   ├── main.py              # FastAPI app — endpoints, job lifecycle
│   ├── runner.py            # ThreadPoolExecutor job queue + SSE events
│   ├── pipeline_adapter.py  # Orchestrates extraction → codegen → render → critic → narration
│   ├── storage.py           # Local file storage (data/<job_id>/...)
│   └── models.py            # Pydantic models (JobState, ConceptResult, ...)
├── parser/
│   ├── pdf_parser.py        # PyMuPDF text + section extraction
│   └── figure_extractor.py  # Figure image extraction
├── concepts/
│   └── extractor.py         # LLM concept + shot_list extraction
├── animation/
│   ├── codegen.py           # ManimCodeGenerator (two_pass / dsl / direct)
│   ├── dsl.py               # Typed DSL: Pydantic beat specs → compiled Manim
│   ├── rag.py               # TF-IDF example retrieval (no embeddings needed)
│   ├── renderer.py          # Manim subprocess wrapper + banned-API checks
│   ├── critic.py            # LLM video critic (score + fix instruction)
│   ├── narrator.py          # Script generation + OpenAI TTS + ffmpeg merge
│   └── layout_helpers.py    # Auto-injected Manim helpers (node_row, heatmap, ...)
prompts/
│   ├── manim_storyboard.txt # Pass 1: concept → storyboard
│   ├── manim_codegen.txt    # Pass 2: storyboard → Manim code
│   ├── manim_direct.txt     # Single-pass: concept → Manim code
│   ├── manim_dsl.txt        # DSL mode: concept → JSON spec
│   └── fix_code.txt         # Error-fix prompt
web/                         # Next.js App Router frontend
data/                        # Job outputs (auto-created, gitignored)
papers/                      # Drop PDFs here for testing
```

---

## Data / Output Structure

Each job creates a timestamped directory:

```
data/
└── 20260427_145312_a3f8b2c1/
    ├── _state.json                  # Full job state (polled by UI)
    ├── upload/paper.pdf
    └── concepts/
        └── 00/
            ├── scene.py             # Final Manim code
            ├── storyboard.md        # Storyboard (two_pass / dsl modes)
            ├── video.mp4            # Final narrated video
            ├── subtitles.vtt        # WebVTT subtitles
            ├── critique.md          # Critic report
            ├── compare_two_pass/    # Compare-mode renders
            ├── compare_dsl/
            ├── compare_direct/
            └── history/             # Render history (error fixes, critic fixes)
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `openai` | Provider for concept extraction (`openai` / `anthropic` / `ollama`) |
| `LLM_MODEL` | `gpt-4o` | Model for concept extraction |
| `CODEGEN_PROVIDER` | `openai` | Provider for codegen, critic, narrator |
| `CODEGEN_MODEL` | `gpt-4o` | Model for codegen, critic, narrator |
| `OPENAI_API_KEY` | — | Required for OpenAI provider + TTS narration |
| `ANTHROPIC_API_KEY` | — | Required for Anthropic provider |

Narration (TTS) requires `CODEGEN_PROVIDER=openai`. It is skipped gracefully for other providers.

---

## UI Options

| Option | Description |
|---|---|
| **Concepts** | Max concepts to extract (1–8) |
| **Quality** | Manim render quality: Low / Medium / High |
| **Parallel concepts** | How many concepts to render simultaneously |
| **Render retries** | Max LLM fix attempts per failed render (default 6) |
| **Generation mode** | Two-pass / DSL / Direct / Compare all three |
| **Animate figures** | Extract paper figures and use as visual reference |
| **Voice narration** | Add AI voiceover + subtitles (requires OpenAI) |
