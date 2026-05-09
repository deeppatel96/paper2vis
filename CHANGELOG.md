# Changelog

All notable changes to paper2vis are documented here.

## [v1.1.0] — 2026-05-08

### Added
- **Supabase job persistence** — completed jobs survive redeployments; each user sees only their own jobs
- **LLM live preview panel** — storyboard, generated code, and critique appear in real time as the pipeline runs
- **Novelty focus mode** — auto-detects the paper's novel contribution and steers concept extraction toward it; user hint field for extra guidance
- **User-selectable models** — extraction and codegen models are now user-configurable in the upload form; pro-only models gated by tier
- **Pro-tier defaults** — pro users get high quality, 8 concepts, 3 parallel workers, RAG on, and best models pre-selected
- **Job tags** — jobs are tagged with generation mode, tier, quality, model names, and feature flags (novelty, rag, concept-pick)
- **Version badge** — current version shown in upload UI, linked to the GitHub tag
- **Invite code system** — single-use invite codes upgrade users to Pro on redemption
- **Admin settings panel** — configure per-tier models and limits without redeploying
- **PDF preview** — uploaded PDF shown inline in the drop zone
- **Concept selection gate** — pipeline can pause for the user to pick which concepts to animate
- **Novel contribution banner** — detected novelty shown on the job page with no extra LLM calls
- **Per-concept LLM output tabs** — storyboard / code / critique viewable live during generation

### Fixed
- Pinned Docker base image to `python:3.12` to avoid missing wheels on Python 3.14
- Added `build-essential` and `gcc` to Dockerfile for `pycairo` compilation
- Auth tokens now passed on all frontend API calls (job page, sidebar, concept selection, paper tab)
- Invite code redemption: upsert user row before updating `invite_codes` to satisfy FK constraint
- Pro-only model gate defaults to pro when usage fetch fails (local dev)
- Settings panel now surfaces the real error instead of swallowing it

---

## [v1.0.0] — 2026-04-01

### Added
- Initial release: PDF → Manim animation pipeline
- Three generation modes: two-pass (storyboard → code), DSL (typed spec → compiler), direct
- "Compare all" mode runs all three and keeps the best result
- Critic loop: automated quality scoring and fix iterations
- Visual diff: frame comparison between paper figure and rendered animation
- Voice narration with TTS and subtitle generation
- RAG-based style examples (3b1b-style reference injection)
- Concept map animation showing relationships between extracted concepts
- Clerk authentication with mini/pro tier system
- Railway (backend) + Vercel (frontend) + Supabase (DB) deployment stack
- Lean proof enrichment for the primitive animation mode
