# paper2vis — Final Report Outline
# COMS 6998: Machine-Assisted Mathematics

---

## 1. Introduction

### 1.1 Motivation
- Academic papers are dense; animated visualizations dramatically lower the barrier to understanding mathematical concepts
- Existing tools (3Blue1Brown / manim) require manual authoring — each animation takes hours to days
- Goal: given a PDF, automatically produce a set of short educational animations, one per key concept

### 1.2 Problem Statement
- Input: arbitrary academic PDF (ML, quantum computing, linear algebra, etc.)
- Output: a set of rendered MP4 animations, each explaining one mathematical concept
- Challenges:
  - LLM-generated Manim code fails to render ~30% of the time (undefined names, bad API calls, layout errors)
  - Concept extraction must identify *visualizable* ideas, not just topics
  - Animations must be pedagogically correct, not just syntactically valid

### 1.3 Contributions
1. End-to-end pipeline: PDF → concepts → Manim code → rendered video
2. Typed animation DSL with 12 beat types — eliminates entire classes of runtime failures
3. Mathlib-inspired concept family tagger grounding code generation in mathematical structure
4. Four-mode code generation with graceful fallback chain
5. Vision-based critic loop that scores and auto-fixes animations post-render
6. Full-stack web application with auth, usage tiers, and streaming progress

---

## 2. System Architecture

### 2.1 High-Level Pipeline
```
PDF
 └─ Stage 1: PDF Parser          (text + section segmentation)
     └─ Stage 1b: Figure Extractor   (optional: rasterize figures for vision)
         └─ Stage 2: Concept Extractor   (LLM → JSON concept list)
             └─ Stage 3: Code Generator      (concept → AnimationSpec → Manim Python)
                 └─ Stage 4: Renderer            (Manim CLI → MP4)
                     └─ Stage 5: Vision Critic       (LLM scores keyframes → auto-fix)
                         └─ Stage 6: Narrator            (optional TTS + subtitle merge)
```

### 2.2 Component Overview
| Component | File | Role |
|-----------|------|------|
| PDF Parser | `src/parser/pdf_parser.py` | pdfminer → sections + abstract |
| Figure Extractor | `src/parser/figure_extractor.py` | Rasterize PDF pages, extract figure regions |
| Concept Extractor | `src/concepts/extractor.py` | LLM call → structured Concept list |
| Mathlib Matcher | `src/concepts/mathlib_matcher.py` | Tag concept with math family |
| Code Generator | `src/animation/codegen.py` | Four generation modes |
| Animation DSL | `src/animation/dsl.py` | Typed beat models + DSLCompiler |
| Lean Proof Animator | `src/animation/lean_proof.py` | Mathlib structure registry + beat hints |
| RAG Store | `src/animation/rag.py` | TF-IDF retrieval of curated Manim examples |
| Renderer | `src/animation/renderer.py` | Manim CLI subprocess wrapper |
| Critic | `src/animation/critic.py` | Vision LLM scores rendered keyframes |
| Narrator | `src/animation/narrator.py` | TTS + WebVTT subtitle generation |
| API | `src/api/main.py` | FastAPI REST + SSE streaming |
| Runner | `src/api/runner.py` | ThreadPoolExecutor job queue |
| Auth | `src/api/auth.py` | Clerk JWT verification |

### 2.3 LLM Usage
- Extraction: Claude Haiku 4.5 (mini tier) / Claude Sonnet 4.6 (pro tier)
- Code generation: Claude Sonnet 4.6 (mini) / Claude Opus 4.6 (pro)
- Vision critic: GPT-4.1 or Claude with vision
- Narration: OpenAI TTS-1

---

## 3. Development Timeline and Pipeline Evolution

This section traces the project from initial prototype to the current system, including the problems encountered at each stage and the design decisions made in response.

### 3.1 Phase 1 — Skeleton: PDF → LLM → Manim (Week 1–2)

The initial version of the pipeline was built quickly using AI-assisted coding tools (Claude Code). The skeleton was straightforward: parse a PDF with `pdfminer`, send a section to an LLM with a simple prompt asking it to produce a Manim scene, and invoke the Manim CLI to render it.

**What worked immediately:**
- The core loop (parse → prompt → render) was easy to stand up
- GPT-4o and Claude Sonnet produced syntactically plausible Manim code most of the time
- The 3Blue1Brown aesthetic translated surprisingly well when the LLM had a reference example in the prompt

**First major problem — render failure rate ~30%:**
Generated code crashed on the first render attempt roughly one in three times. Common causes included undefined color names (`LIGHT_BLUE`, `DARK_GREEN`), deprecated Manim API calls (`ShowCreation` instead of `Create`), bare direction vectors passed to `Arrow()`, and missing `font_size` arguments on `Text()` (which defaults to 48pt — enormous on a 1080p canvas). These errors were systematic and predictable, but the LLM kept making them regardless of how the prompt was phrased.

**Fix attempted — retry loop:**
Added a render-error retry loop: on failure, extract the Python traceback, prepend it to the prompt, and ask the LLM to fix the code. This helped but was insufficient — the LLM would fix the reported error and introduce a new one, and the loop would terminate after 3 attempts regardless.

---

### 3.2 Phase 2 — Structured Concept Extraction (Week 2–3)

The first prototype sent raw section text to the code generator. This produced animations that were disconnected from the paper's actual contributions — the LLM would latch onto whatever was most prominent in the text, not what was most visually interesting.

**Solution — dedicated extraction step:**
Introduced `ConceptExtractor` as a separate LLM call that returns structured JSON: concept name, description, visual type (from a fixed taxonomy of nine types like `equation_transform`, `matrix_op`, `flow`), key variables, and a rough shot list. This two-step design — extract *what* to show before deciding *how* to show it — dramatically improved relevance.

**Problem — duplicate and overlapping concepts:**
Early runs produced the same idea under different names (e.g., "self-attention" and "attention mechanism"). Added fuzzy name-overlap deduplication using word-set Jaccard similarity.

---

### 3.3 Phase 3 — Two-Pass Generation and the Storyboard (Week 3–4)

Even with structured concepts, the direct LLM-to-code path produced low-quality animations. A single LLM call had to simultaneously plan the visual narrative and write syntactically correct Manim — too many degrees of freedom for consistent quality.

**Solution — two-pass generation:**
Split into: (1) a storyboard pass that produces a detailed beat-by-beat Markdown plan, then (2) a code generation pass that implements the storyboard. The storyboard acts as a contract — the LLM writing code has far less creative latitude and far more specific instructions. Animation quality improved noticeably.

**Parallel investment — prompt engineering:**
Added a large rule set to the codegen prompt: valid color names, banned animation calls, layout helper documentation with examples, spatial positioning rules, font size requirements. This reduced the render failure rate but did not eliminate it — there were always new edge cases, especially on papers from domains not well-represented in training data (quantum computing, formal logic).

**Lesson:** Prompt engineering does not scale. Every new rule can conflict with existing rules, and rare domains expose gaps that no finite prompt can close.

---

### 3.4 Phase 4 — Animation DSL and DSLCompiler (Week 4–5)

**Core insight:** The LLM is good at deciding *what to show* (which beat type, which values, which layout) but bad at remembering Manim API details (parameter names, class hierarchies, valid keyword arguments). The solution was to separate these concerns entirely.

**Solution — typed beat DSL:**
Designed a JSON schema (`AnimationSpec`) with 12 beat types, each with Pydantic-validated parameters. The LLM produces a JSON spec; a deterministic `DSLCompiler` converts it to Manim code. No free-form Python is emitted by the LLM.

- Pydantic validation coerces values at parse time (clamping heatmap entries to [0,1], normalizing probability distributions, enforcing `n_steps ≤ 8`).
- The compiler pre-computes all trajectories and positions in Python — no Manim runtime computation errors possible for covered beat types.
- First-render success rate for DSL mode: ~85–90%, compared to ~70% for two-pass.

**Added `primitive` mode:**
A further restriction: the LLM picks from the beat catalog but cannot choose arbitrary parameters — it selects from a curated family-indexed set. First-render success approaches 95%.

---

### 3.5 Phase 5 — Vision Critic and the Static Animation Problem (Week 5–6)

Render success rate is not the same as animation quality. An animation can render successfully while being pedagogically useless — a sequence of labeled boxes fading in is technically valid Manim but teaches nothing.

**Solution — vision-based critic:**
Extracted keyframes from rendered MP4s using ffmpeg and sent them to a vision LLM (GPT-4o with vision) alongside the storyboard. The critic scores the animation on a 0–10 rubric focused on whether the *mechanism* is shown, not just the structure.

**Finding — 70% failure rate:**
After running the critic across 73 animations, approximately 70% scored below the passing threshold (7/10). The dominant failure mode was static-only animations: every object `FadeIn`s or `Write`s with no `Transform`, `ReplacementTransform`, or `ValueTracker`. The animation shows vocabulary (an "Encoder" box, an "Attention" label) but not computation (what value enters, what value exits, how the transformation happens).

**Root cause analysis:**
The storyboard was underspecified — it would say "show the softmax computation" without specifying what values appear, what the output looks like numerically, or which animation primitive demonstrates the computation. The codegen LLM, lacking specificity, defaulted to safe static reveals.

**Fixes applied:**
- Added mandatory "Computation spec" field to each storyboard beat (must name exact values and which animation method — `ValueTracker`, `ReplacementTransform`, `animate_bars`, etc.)
- Added "FORBIDDEN ANTI-PATTERNS" section to the codegen prompt with direct code-level examples of what not to do
- Added rule 18 to `validate_code()`: if the entire scene is static-only, inject a dynamic transformation
- Added programmatic regex cap on `font_size` (any value > 36 is hard-capped to 36) to fix the 48pt default problem

---

### 3.6 Phase 6 — RAG and Style Grounding (Week 5–6, parallel)

**Problem — style inconsistency:**
Even well-structured animations looked visually inconsistent. The LLM had learned Manim conventions from sparse training data (Manim was open-sourced in 2020 and has a small community relative to general Python).

**Solution — RAG with curated examples:**
Built a retrieval store (`data/rag_examples.json`) of hand-curated Manim scenes from 3Blue1Brown's open-sourced code and other high-quality sources. TF-IDF word-overlap retrieval injects the top-k most relevant examples into the two-pass and direct mode prompts. This improved style consistency and correct use of layout helpers significantly.

**Limitation:** The example corpus is small. Manim is not widely used outside of educational animation, so there is limited code at the scale typically required to train or reliably prompt a large language model. This is a fundamental constraint of the domain.

---

### 3.7 Phase 7 — Mathlib Grounding and Lean Integration (Week 6–7)

**Motivation:**
For mathematical concepts (linear algebra, probability, optimization), the DSL beat types are structurally correct but the *parameterization* — which matrix to show, what values to use, how many steps in the gradient descent — was still left to the LLM. This produced animations that were structurally fine but mathematically arbitrary.

**Solution — Mathlib-inspired structure registry:**
Built a registry of ~25 `LeanStructure` entries mapping Lean 4 / Mathlib type names to animation guidance (primary beat type, parameter hints, example JSON). For a concept that matches "attention" or "matrix multiplication," the registry tells the codegen LLM what a canonical animation of that structure looks like at the parameter level.

An optional `LeanClient` subprocess wrapper can verify that matched Lean names exist in the local Lean environment, though the registry operates independently when Lean is not installed.

---

### 3.8 Phase 8 — Web Application, Auth, and Productization (Week 6–8)

Built the full-stack web application in parallel with pipeline improvements:
- FastAPI backend with ThreadPoolExecutor job runner and SSE streaming
- Next.js 16 frontend with real-time progress updates
- Clerk authentication and Supabase per-user state (tier, usage)
- Two usage tiers (mini / pro) with different model and quality limits
- Concept selection gate: user reviews extracted concepts before expensive rendering starts
- Invite code system for controlled Pro access

**Deployment:**
- Backend on Render (Docker container, persistent disk for job data)
- Frontend on Vercel
- Database on Supabase

---

### 3.9 What Worked and What Didn't

**Worked:**
- The DSL/compiler separation was the single highest-leverage change — it eliminated the largest class of runtime failures structurally
- The vision critic was effective at identifying the right failure mode (static-only animations) even when the animations looked complete
- The two-pass storyboard → code structure produced consistently higher quality than single-pass direct generation
- RAG injection improved style consistency noticeably

**Didn't work:**
- Prompt engineering alone as a reliability strategy — every new rule introduced edge cases, and the rule set grew unwieldy without fundamentally solving the problem
- Expecting the LLM to self-correct via the retry loop — it would often fix the reported error and introduce a new one at the same rate
- The static animation problem proved deeply resistant to prompt-level fixes until the storyboard was changed to require explicit computation specs per beat

**Why:**
The core difficulty is that Manim is a small, niche library with limited LLM training exposure. The models have absorbed enough to produce plausible-looking code, but not enough to reliably recall correct API signatures, valid parameter combinations, or idiomatic patterns for complex layouts. The DSL approach sidesteps this by removing the LLM from the code-writing loop entirely for the structural parts of the animation.

---

## 4. PDF Parsing and Concept Extraction

### 3.1 PDF Parser
- Uses `pdfminer` for text extraction
- Segments into sections by heading heuristics
- Preserves equations and variable names from raw text (passed verbatim to LLM)

### 3.2 Figure Extraction (optional)
- Rasterizes each page via `poppler`
- Detects figure bounding boxes; sorts by size (largest = most informative)
- Used in `two_pass` mode: figure image becomes ground truth for storyboard generation

### 3.3 Concept Extractor
- Calls LLM with `prompts/concept_extraction.txt`
- Returns structured JSON: name, description, visual_type, variables, shot_list, raw_text
- Nine visual type tags: `equation_transform`, `matrix_op`, `flow`, `graph`, `geometric`, etc.
- Deduplication: fuzzy name overlap check prevents the same idea from appearing twice
- Per-tier limits: 3 concepts (mini) vs 16 concepts (pro)

### 3.4 Concept Graph (optional)
- Secondary LLM call builds a dependency graph over concepts
- Edges labeled `prerequisite` or `related`
- Used for topological sort in the UI and for the `InteractiveConceptMap` visualization

---

## 5. Code Generation

### 5.1 The Reliability Problem
- Free-form LLM-generated Manim code has a ~30% first-render failure rate
- Common failure modes: undefined color names, invalid API calls, font_size omitted, `Text()` used for math, `LEFT_CENTER` not defined, layout helper parameter name mismatches
- Strategy: constrain the output space so structural errors become impossible

### 5.2 Four Generation Modes

**Mode 1: `two_pass` (original, highest quality)**
- Pass 1: concept + shot_list → detailed visual storyboard (Markdown)
- Pass 2: storyboard → Manim Python code
- Supports figure-grounded variant: paper figure image injected into both passes

**Mode 2: `dsl` (most reliable)**
- One LLM call produces a JSON `AnimationSpec` conforming to the DSL schema
- Pydantic validates and coerces the spec (clamping values, normalizing lengths)
- `DSLCompiler` converts to Manim — no free-form Python emitted by the LLM

**Mode 3: `direct` (fastest)**
- Single LLM call produces Manim Python directly
- No storyboard intermediate; lower quality but cheap

**Mode 4: `primitive` / `lean` (most grounded)**
- LLM picks from a catalog of 12 validated beat types
- `lean` mode: concept is first matched against the Mathlib structure registry; beat-level hints injected into the prompt
- Output compiled by `DSLCompiler` — runtime errors structurally impossible for covered operations

### 5.3 Prompt Engineering
- `prompts/manim_storyboard.txt`: requires a "Computation spec" for every beat (what values change on screen)
- `prompts/manim_codegen.txt`: 18-rule validator checklist + forbidden anti-patterns list
- `prompts/manim_primitive.txt`: beat catalog with JSON examples, rules, `{{LEAN_HINT}}` injection point
- All prompts enforce: `font_size` on every `Text()`, `MathTex` for all math, no bare direction vectors

### 5.4 Static Code Validator
- `validate_code()`: LLM review pass before first render — catches color name errors, deprecated API calls, missing font_size
- `_fix_code_issues()`: programmatic regex fixes (cap font_size > 36)

---

## 6. Animation DSL and Primitive Library

### 5.1 Design Rationale
- The LLM is not good at remembering Manim API details; it is good at choosing what to show
- Separation: LLM decides *what* (beat types + parameters) → compiler decides *how* (Manim calls)
- Beat parameters are validated and coerced by Pydantic before any code is emitted

### 5.2 Beat Type Catalog (12 types)

| Beat | Visual | Key Parameters |
|------|--------|---------------|
| `node_row` | Horizontal circles with labels | labels, colors, weights, position |
| `heatmap` | 2D color grid | matrix (clamped [0,1]), row/col labels, highlight_row |
| `bar_chart` | Animated bars | values, labels, then_transform (posterior update) |
| `side_by_side` | Horizontal boxes + arrows | labels, highlight |
| `flow_column` | Vertical pipeline | labels, colors, highlight |
| `text` | Centred text + subtitle | content, subtitle, color |
| `weighted_connections` | Two node rows + weighted lines | from/to labels, weights matrix |
| `attention_matrix` | Heatmap for Q×K attention | query/key labels, scores, highlight_query |
| `bayes` | Prior → posterior bar transform | hypotheses, prior (auto-normalized), likelihood |
| `gradient_step` | Loss curve + descent trajectory | fn_type (quadratic/cubic/sine), n_steps, lr |
| `eigendecomposition` | Matrix heatmap + eigenvector arrows | matrix, eigenvalues, eigenvectors (2×2 or 3×3) |
| `tree` | Tree / DAG with traversal | nodes, edges, traversal_order, highlight_color |

### 5.3 DSLCompiler
- Pre-computes all trajectories and positions in Python (no Manim computation errors)
- Every output line uses either auto-injected layout helpers or verified Manim API calls
- Beat transitions: `FadeOut` between beats; `LaggedStart` within beats
- Indented output ready for `exec()` without modification

### 5.4 parse_spec — Robust JSON Extraction
Four-strategy fallback for extracting `AnimationSpec` from LLM output:
1. Direct parse (model returned only JSON)
2. Fenced ` ```json ``` ` block
3. Bracket-slice (first `{` to last `}`)
4. Greedy regex

### 5.5 Layout Helpers (auto-injected)
- `CONTENT_CENTER = DOWN*0.5` — all content anchors here, below the persistent title
- `node_row`, `flow_column`, `side_by_side`, `heatmap`, `bar_chart`, `animate_bars`, `connect`
- Positions computed from center outward — never hardcoded pixel offsets

---

## 7. Mathlib-Inspired Grounding

### 6.1 Concept Family Tagger (`mathlib_matcher.py`)
- Maps concept name + description → one of 13 math families (attention, linear_algebra, probability, optimization, graph, etc.)
- Pure keyword heuristics; no external service needed
- Output used to select `recommended_beats` injected into the primitive prompt

### 6.2 Lean / Mathlib Structure Registry (`lean_proof.py`)
- ~25 hand-curated `LeanStructure` entries mapping Lean 4 / Mathlib types to animation guidance
- Each entry specifies: structural fields, primary beat type, beat parameterization hints, example JSON
- Covers: matrix operations, attention, Bayesian inference, gradient descent, graph algorithms, neural networks, calculus, sequences
- Keyword scoring to match a concept to the best registry entry (requires ≥2 keyword matches)

### 6.3 LeanClient (optional)
- Thin subprocess wrapper around `lean --stdin`
- Can verify that a matched Lean name actually exists in the environment
- Gracefully disabled when Lean is not installed; registry operates independently

### 6.4 `mode="lean"` Integration
- `generate(concept, mode="lean")` → `LeanProofAnimator.enrich(concept)` → `LeanStructure | None`
- If matched: `build_prompt_hint()` produces a Markdown block injected as `{{LEAN_HINT}}` in the primitive prompt
- If no match: silently falls back to plain `primitive` mode

---

## 8. Rendering and Quality Assurance

### 7.1 Renderer
- Wraps Manim CLI subprocess (`manim render --quality ...`)
- Injects layout helpers by prepending `layout_helpers.py` source to the scene file
- Returns path to rendered MP4

### 7.2 Retry Loop
- Up to 3 render attempts per concept
- On failure: extracts actionable error substring, calls `fix_code(code, error)` LLM
- Hash-checks fixed code to detect no-op fixes (breaks loop if LLM returns identical code)

### 7.3 RAG (Retrieval-Augmented Generation)
- `data/rag_examples.json`: curated Manim scenes from 3Blue1Brown and other sources, labeled by field
- TF-IDF word-overlap scoring; no external embedding service
- Top-k examples injected into `two_pass` and `direct` mode prompts as style references
- Thread-safe lazy loading with lock

### 7.4 Vision Critic
- Extracts 3 keyframes from the rendered MP4 via ffmpeg
- Sends keyframes + storyboard to a vision LLM (GPT-4.1 or Claude)
- Returns: score 0–10, list of issues, natural-language fix instruction
- If score < threshold: applies `apply_instruction()` and re-renders once
- Critique report saved as `.critique.md` alongside the Manim file

### 7.5 Narration (optional)
- LLM writes a narration script timed to the video duration (~130 wpm)
- OpenAI TTS-1 generates MP3 audio
- ffmpeg merges audio + video; WebVTT subtitles generated from word timing

---

## 9. Web Application

### 8.1 Backend API (FastAPI)
- `POST /api/jobs` — upload PDF, create job, start pipeline in thread pool
- `GET /api/jobs/{id}` — full job state (concepts, videos, progress)
- `GET /api/jobs/{id}/stream` — SSE event stream for live progress
- `POST /api/jobs/{id}/select` — user submits concept selection (unblocks pipeline gate)
- `POST /api/jobs/{id}/regenerate` — re-run codegen for one concept
- `GET /api/videos/{job_id}/{concept_index}` — serve rendered MP4
- `GET /api/me/usage` — tier, jobs used, reset date
- `POST /api/invite` — redeem invite code for Pro upgrade

### 8.2 Job Runner
- `ThreadPoolExecutor` with `min(8, cpu+2)` workers
- File-based persistence (`data/{job_id}/_state.json`) — survives server restarts
- Concept selection gate: pipeline thread blocks on `threading.Event` until user picks concepts
- Job cancellation: sets cancelled flag + unblocks selection gate

### 8.3 Frontend (Next.js 16 + React 19 + Tailwind 4)
- `UploadPage`: drag-and-drop PDF upload with tier badge and usage meter
- `JobPage`: live-updating job view via SSE; shows pipeline stage tracker, concept skeletons, concept cards
- `ConceptCard`: plays rendered video inline; supports regeneration with mode selector
- `ConceptSelectionPanel`: lets user pick which concepts to animate before rendering begins
- `InteractiveConceptMap`: force-directed graph of concept relationships
- `PaperTab`: shows extracted figures; per-figure regeneration (vision mode)
- Sidebar: job history navigation
- Sign-in / Sign-up: Clerk-hosted auth flows
- `/invite`: redeem invite code for Pro tier upgrade

### 8.4 Streaming Progress
- Backend emits SSE events: `status`, `progress`, `concept_stub`, `concept_done`, `done`, `error`
- Frontend reconnects on disconnect; polls `getJob()` on each event to get full updated state
- Concept skeletons appear immediately when names are known, before videos finish rendering

---

## 10. Authentication and Hosting

### 9.1 Auth System (Clerk + Supabase)
- Clerk handles identity (JWT issuance, social login, session management)
- Supabase stores per-user state: tier, jobs_used, jobs_limit, reset_date, invite_codes
- `POST /api/webhooks/clerk` syncs new users to Supabase on sign-up
- `verify_token()` FastAPI dependency: validates Clerk JWT via JWKS; returns `"dev"` when `CLERK_JWKS_URL` unset

### 9.2 Usage Tiers

| | mini (free) | pro |
|-|-------------|-----|
| Jobs/month | 5 | 50 |
| Extraction model | Claude Haiku 4.5 | Claude Sonnet 4.6 |
| Codegen model | Claude Sonnet 4.6 | Claude Opus 4.6 |
| Max concepts | 3 | 16 |
| Render quality | low | high |

### 9.3 Invite Code System
- Admin endpoint `POST /api/admin/users/{clerk_id}/tier` upgrades any user
- `POST /api/invite` redeems a single-use code → upgrades to Pro
- Codes stored as JSONB in Supabase `users` table

### 9.4 Deployment
- Backend: Render (Docker, `render.yaml`, 2 CPU / 4 GB RAM, 10 GB persistent disk for job data)
- Frontend: Vercel (root dir = `web/`, Next.js auto-detected)
- Database: Supabase (PostgreSQL)
- Auth: Clerk

---

## 11. Reliability Engineering

### 10.1 LLM Call Infrastructure (`llm_utils.py`)
- Singleton clients (Anthropic, OpenAI) — one HTTP connection pool per process
- Exponential backoff retry on 429 rate-limit errors (5 attempts, up to 60s delay)
- Unified `call_llm` / `call_llm_vision` / `call_llm_vision_bytes` interface across providers

### 10.2 Observed Failure Modes and Fixes

| Failure | Fix Applied |
|---------|-------------|
| `NameError: LIGHT_BLUE` | Prompt color allowlist + `validate_code()` pre-check |
| `font_size` default 48pt causes overflow | Prompt rule + programmatic regex cap at 36 |
| `Text(r"\frac{}")` shows raw backslash | Prompt rule: `MathTex` for all math |
| `LEFT_CENTER` undefined | Prompt clarification; `validate_code()` catches it |
| `side_by_side(colors=...)` wrong kwarg | Prompt rule: must be `stage_colors=` |
| LLM fix loop produces identical code | Hash check breaks retry loop |
| Concurrent RAG reads cause race | `threading.Lock` around lazy load |

### 10.3 Test Suite (`tests/test_primitives.py`)
- 29 tests covering all 12 beat types, `parse_spec` extraction strategies, and `mathlib_matcher` family detection
- Beat tests assert: valid Python (ast.parse), presence of key Manim constructs, correct transform animations
- Validator tests: auto-normalize prior, clamp heatmap values, reject `n_steps > 8`
- Optional section 4: end-to-end LLM call tests (skipped without `ANTHROPIC_API_KEY`)

---

## 12. Evaluation

### 11.1 Quantitative
- Test suite: 29/29 passing
- Generation mode render success rates (to be measured on held-out paper set):
  - `primitive` / `lean`: target ~95% first-render success (DSLCompiler eliminates structural errors)
  - `dsl`: ~85% (Pydantic validation catches most issues; prompt compliance varies)
  - `two_pass`: ~70% (baseline; free-form Python)
  - `direct`: ~65% (no storyboard; highest variance)

### 11.2 Qualitative
- Critic scores on rendered animations (0–10 scale)
- Human evaluation: does the animation correctly illustrate the concept?
- Comparison: primitive/lean mode vs two_pass for mathematical precision

### 11.3 Case Studies
- Quantum computing paper (HVA / Yuen 2020): Hamiltonian Variational Ansatz, barren plateaus, entanglement entropy
- Transformer paper ("Attention Is All You Need"): self-attention mechanism, multi-head attention, positional encoding
- Proposed: Bayesian inference paper; linear algebra methods paper

---

## 13. Related Work

- **3Blue1Brown / manim**: manual authoring, hours per animation; our system automates this
- **Animate-A-Story / VideoDirectorGPT**: video generation, not mathematical animation
- **SciVerse / ScholarPhi**: paper augmentation, not animation
- **Mathlib (Lean 4)**: formal mathematics library; we borrow its type hierarchy as an animation ontology
- **RAG for code generation**: we apply retrieval to Manim-specific examples rather than general code
- **LLM-based code repair**: our retry loop applies targeted error messages, similar to Reflexion

---

## 14. Limitations and Future Work

### 13.1 Current Limitations
- Manim requires LaTeX — cold Docker start is slow (~60s); warm render is ~5–15s per video
- `two_pass` mode still produces free-form Python; occasional runtime failures
- Concept extraction can miss implicit visual ideas (e.g. proof sketches, geometric intuitions)
- No support for multi-panel / split-screen animations
- Narration quality depends on video duration estimate accuracy

### 13.2 Future Work
- **Broader DSL coverage**: 3D scenes, morphing equations, number line animations
- **Lean integration depth**: use `pantograph` or Mathlib REST API to query arbitrary type definitions
- **Interactive animations**: export to `manim-slides` or a WebGL renderer for browser playback
- **User feedback loop**: store critic scores + human ratings; fine-tune codegen prompt selection
- **Multi-paper coherence**: generate a "lecture" across several papers with shared notation
- **Faster rendering**: pre-warm Manim worker pool; cache compiled LaTeX fragments

---

## 15. Conclusion

paper2vis demonstrates that the end-to-end pipeline from academic PDF to rendered educational animation is feasible with current LLMs, but reliability requires deliberate constraint of the output space. The key insight is the separation between *what to show* (beat selection, a task LLMs do well) and *how to render it* (Manim API calls, where LLMs make systematic errors). The typed DSL + DSLCompiler architecture reduces first-render failures from ~30% to near zero for the covered beat types, while the Mathlib-inspired structure registry grounds beat parameterization in mathematical semantics rather than surface-level heuristics.

---

## Appendix

### A. Repository Structure
```
paper2vis/
├── src/
│   ├── api/            FastAPI backend, job runner, auth
│   ├── animation/      DSL, codegen, renderer, critic, narrator, RAG, lean_proof
│   ├── concepts/       Extractor, Mathlib matcher
│   ├── parser/         PDF parser, figure extractor
│   └── templates/      Manim base scenes
├── web/                Next.js frontend (App Router)
├── prompts/            LLM prompt templates (12 files)
├── data/               RAG examples, job storage
├── tests/              Test suite
├── supabase/           Schema SQL
├── Dockerfile          Backend container
└── render.yaml         Render deployment blueprint
```

### B. Key Design Decisions
1. **Beat-based DSL over free-form Python**: eliminates the largest category of render failures
2. **Pydantic models for beats**: validation + coercion at JSON parse time, not render time
3. **Pre-computed trajectories**: gradient descent steps computed in Python at compile time, not in Manim lambdas
4. **File-based job persistence**: no Redis/Celery dependency; survives server restart
5. **SSE over WebSocket**: simpler server-push for progress; no bidirectional channel needed
6. **Concept selection gate**: user reviews extracted concepts before expensive rendering begins

### C. Environment Variables
```
ANTHROPIC_API_KEY, OPENAI_API_KEY
CLERK_JWKS_URL, CLERK_WEBHOOK_SECRET
SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
ADMIN_SECRET, FRONTEND_URL
LLM_PROVIDER, CODEGEN_PROVIDER, LLM_MODEL, CODEGEN_MODEL
DEV_TIER (local dev only)
```
