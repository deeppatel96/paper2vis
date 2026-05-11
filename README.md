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
- **Anthropic API key** (Claude for extraction/codegen) and/or **OpenAI API key** (TTS narration)

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
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6

# Code generation
CODEGEN_PROVIDER=anthropic
CODEGEN_MODEL=claude-sonnet-4-6

ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...        # required for voice narration (TTS)
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
2. **Concept Extraction** — LLM reads each section and identifies visualizable concepts with shot lists
3. **Code Generation** — Multiple modes available (select via checkboxes in UI; multiple modes render side-by-side for comparison):
   - **Two-pass** (default): storyboard → Manim code. Best quality.
   - **Typed DSL**: concept → typed JSON spec → compiled Manim. Most reliable structure, no free-form Python.
   - **Direct**: concept → Manim code in one shot. Fastest.
   - **Lean/Mathlib** *(experimental)*: concept → Lean 4 proof skeleton → Manim proof visualization. For theorem-heavy papers.
4. **RAG injection** — TF-IDF retrieval over curated Manim examples (by scientific field) injected into prompts (opt-in)
5. **Validation** — LLM pre-render checker catches banned APIs, invalid colors, LaTeX usage before Manim runs
6. **Render** — Manim renders the scene; up to 6 retry attempts with LLM error-fixing
7. **Critic loop** — LLM watches the rendered video and proposes targeted fixes (up to 2 passes)
8. **Narration** — OpenAI TTS generates voiceover + WebVTT subtitles synced to video duration

Each animation shows a live pipeline status tracker: **Codegen → Validate → Render → Critic → Narrate**, with per-stage pass/fail indicators and retry counts.

---

## Project Layout

```
src/
├── api/
│   ├── main.py              # FastAPI app — endpoints, job lifecycle
│   ├── runner.py            # ThreadPoolExecutor job queue + SSE events
│   ├── pipeline_adapter.py  # Orchestrates extraction → codegen → render → critic → narration
│   ├── storage.py           # Local file storage (data/<job_id>/...)
│   ├── auth.py              # Clerk JWT verification + tier logic
│   ├── webhooks.py          # Clerk webhook → Supabase user sync
│   └── models.py            # Pydantic models (JobState, ConceptResult, ...)
├── parser/
│   ├── pdf_parser.py        # PyMuPDF text + section extraction
│   └── figure_extractor.py  # Figure image extraction
├── concepts/
│   └── extractor.py         # LLM concept + shot_list extraction
├── animation/
│   ├── codegen.py           # ManimCodeGenerator (two_pass / dsl / direct / lean)
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
            ├── compare_two_pass/    # Multi-mode comparison renders
            ├── compare_dsl/
            ├── compare_direct/
            └── history/             # Render history (error fixes, critic fixes)
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | Provider for concept extraction (`openai` / `anthropic` / `ollama`) |
| `LLM_MODEL` | `claude-sonnet-4-6` | Model for concept extraction |
| `CODEGEN_PROVIDER` | `anthropic` | Provider for codegen, critic, narrator |
| `CODEGEN_MODEL` | `claude-sonnet-4-6` | Model for codegen, critic, narrator |
| `ANTHROPIC_API_KEY` | — | Required for Anthropic provider |
| `OPENAI_API_KEY` | — | Required for OpenAI provider + TTS narration |
| `CLERK_JWKS_URL` | — | Clerk JWKS endpoint for JWT auth (omit for local dev — no auth required) |
| `DEV_TIER` | `pro` | Tier used in local dev mode (`mini` / `pro`) |
| `SUPABASE_URL` | — | Supabase project URL (for user/job persistence in production) |
| `SUPABASE_SERVICE_ROLE_KEY` | — | Supabase service role key |
| `ADMIN_SECRET` | — | Secret for `/admin` UI and `x-admin-secret` protected endpoints |

Narration (TTS) requires `CODEGEN_PROVIDER=openai` or `OPENAI_API_KEY` set. It is skipped gracefully otherwise.

---

## UI Options

| Option | Description |
|---|---|
| **Concepts** | Max concepts to extract (1–16 depending on tier) |
| **Quality** | Manim render quality: Low / Medium / High |
| **Parallel concepts** | How many concepts to render simultaneously |
| **Render retries** | Max LLM fix attempts per failed render (default 6) |
| **Generation mode** | Checkboxes: Two-pass / Typed DSL / Direct / Lean. Select multiple to render side-by-side for comparison. |
| **Animate figures** | Extract paper figures and use as visual grounding reference |
| **Voice narration** | Add AI voiceover + subtitles (requires OpenAI TTS) |
| **Style examples (RAG)** | Inject curated Manim examples into prompts via TF-IDF retrieval |
| **Concept selection** | Pause after extraction to manually pick which concepts to animate |
| **Novelty focus** | Bias extraction toward the paper's novel contributions |

---

## Auth & Tiers (Production)

Authentication uses [Clerk](https://clerk.com). Two tiers are supported:

| Tier | Jobs/month | Max concepts | Quality | Models |
|---|---|---|---|---|
| `mini` | 5 | 3 | Low | haiku-4-5 / sonnet-4-6 |
| `pro` | 50 | 16 | High | sonnet-4-6 / opus-4-6 |

In local dev (no `CLERK_JWKS_URL` set), auth is bypassed and `DEV_TIER` controls the active tier.

Admin UI is available at `/admin` — enter the `ADMIN_SECRET` to view all users and their submitted jobs.

### Deployment

- **Backend**: [Railway](https://railway.app) — Docker, see `Dockerfile`
- **Frontend**: [Vercel](https://vercel.com) — root dir `web/`
- **Database**: [Supabase](https://supabase.com) — run `supabase/schema.sql` once
- **Auth**: [Clerk](https://clerk.com) — configure webhook to `POST /api/webhooks/clerk`
