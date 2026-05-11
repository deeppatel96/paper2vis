"""
Bridges the existing Pipeline to the API layer.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time

logger = logging.getLogger(__name__)
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.api import runner, storage as storage_module
from src.api.runner import JobCancelledError
from src.parser.pdf_parser import PDFParser
from src.parser.figure_extractor import FigureExtractor, ExtractedFigure
from src.concepts.extractor import ConceptExtractor, Concept, normalize_concept_name, names_overlap
from src.animation.codegen import ManimCodeGenerator
from src.animation.renderer import ManimRenderer
from src.animation.critic import ManimCritic
from src.animation.narrator import ManimNarrator


def _check(job_id: str) -> None:
    if runner.is_cancelled(job_id):
        raise JobCancelledError()

def _short_error(exc_str: str, limit: int = 130) -> str:
    """Extract first meaningful line from a render error string."""
    for ln in exc_str.splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and len(ln) > 5:
            return ln[:limit]
    return exc_str[:limit]


def _actionable_error(exc_str: str, max_chars: int = 2000) -> str:
    """Extract the most actionable portion of a Manim error for the fix LLM.

    Manim stderr is verbose. We pull the last traceback block and the final
    error line so the LLM gets signal, not noise.
    """
    # Try to find the last Error/Exception line
    lines = exc_str.splitlines()
    error_lines: list[str] = []
    in_traceback = False
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("Traceback (most recent call last"):
            in_traceback = True
            error_lines = [ln]
        elif in_traceback:
            error_lines.append(ln)
            # An error line ends the traceback block
            if re.match(r"^\s*\w+Error\b|\w+Exception\b", stripped):
                in_traceback = False
        elif re.match(r"^\s*\w+(Error|Exception)\b", stripped):
            error_lines.append(ln)

    if error_lines:
        summary = "\n".join(error_lines)
        return summary[:max_chars]
    return exc_str[:max_chars]


def _code_hash(code: str) -> str:
    return hashlib.md5(code.encode()).hexdigest()


def _diff_trigger(report_json: str, limit: int = 130) -> str:
    """Summarise a visual-diff JSON report into a short trigger string."""
    try:
        data = json.loads(reportjson.strip("`").strip())
        diffs = data.get("differences", [])
        if diffs:
            return "; ".join(str(d) for d in diffs[:2])[:limit]
    except Exception:
        pass
    return "Visual differences detected"


_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": os.environ.get("LLM_MODEL", "gpt-4.1"),
    "ollama": "llama3.1:8b",
}
_MAX_PARALLEL_WORKERS = 8


def _make_tools(options: dict) -> tuple[ManimCodeGenerator, ManimRenderer, ManimCritic, ManimNarrator]:
    provider = options.get("llm_provider") or os.environ.get("LLM_PROVIDER", "openai")
    model = options.get("llm_model") or os.environ.get("LLM_MODEL", "gpt-4.1")
    codegen_provider = options.get("codegen_provider") or os.environ.get("CODEGEN_PROVIDER", provider)
    codegen_model = options.get("codegen_model") or os.environ.get("CODEGEN_MODEL", _DEFAULT_MODELS.get(codegen_provider, model))
    critic_provider = options.get("critic_provider") or codegen_provider
    critic_model = options.get("critic_model") or os.environ.get("CRITIC_MODEL", codegen_model)
    return (
        ManimCodeGenerator(provider=codegen_provider, model=codegen_model),
        ManimRenderer(quality=options.get("quality", "medium_quality")),
        ManimCritic(provider=critic_provider, model=critic_model),
        ManimNarrator(provider=codegen_provider, model=codegen_model),
    )


_MODE_LABELS: dict[str, str] = {
    "two_pass": "Two-pass",
    "dsl":      "Typed DSL",
    "direct":   "Direct",
    "lean":     "Lean/Mathlib",
}


def _generate_multi_mode(
    modes_to_run: list[str],
    codegen, concept, rag_block: str, idx: int, name: str,
    prefix: str, store, renderer, emit, job_id: str, _check,
    narrator=None, options: dict | None = None,
) -> tuple[str | None, str | None, list[dict]]:
    """Generate with multiple modes, render each, return (best_code, storyboard, history_entries).

    Each mode's video is stored as a history entry with a `mode` field so the
    frontend can render them side-by-side for comparison. Runs sequentially.
    """
    storyboard: str | None = None
    best_code: str | None = None
    history_entries: list[dict] = []

    for mode_key in modes_to_run:
        mode_label = _MODE_LABELS.get(mode_key, mode_key)
        _check(job_id)
        try:
            emit({"type": "concept_stage", "index": idx, "stage": "codegen",
                  "status": "running", "detail": mode_label})
            emit({"type": "step", "index": idx, "mode": mode_key,
                  "message": f"[{name}] [{mode_label}] Generating…"})
            _t_mode = time.monotonic()
            if mode_key == "two_pass":
                storyboard = codegen.get_storyboard(concept)
                store.write(f"{prefix}/storyboard.md", storyboard.encode())
                emit({"type": "llm_output", "index": idx, "mode": mode_key, "stage": "storyboard", "content": storyboard})
                emit({"type": "step", "index": idx, "mode": mode_key,
                      "message": f"[{name}] [{mode_label}] Storyboard: {len(storyboard.splitlines())} lines ({time.monotonic()-_t_mode:.1f}s) — generating code…"})
                _t_mode = time.monotonic()
                code = codegen._code_from_storyboard(storyboard, rag_examples=rag_block)
            elif mode_key == "dsl":
                sb = storyboard or codegen.get_storyboard(concept)
                if not storyboard:
                    storyboard = sb
                    store.write(f"{prefix}/storyboard.md", storyboard.encode())
                    emit({"type": "llm_output", "index": idx, "mode": mode_key, "stage": "storyboard", "content": storyboard})
                    emit({"type": "step", "index": idx, "mode": mode_key,
                          "message": f"[{name}] [{mode_label}] Storyboard: {len(storyboard.splitlines())} lines ({time.monotonic()-_t_mode:.1f}s) — compiling DSL…"})
                    _t_mode = time.monotonic()
                code = codegen.generate_dsl(concept, storyboard=sb, rag_examples=rag_block)
            else:
                code = codegen.generate(concept, mode=mode_key, rag_examples=rag_block)

            mode_prefix = f"{prefix}/compare_{mode_key}"
            store.write(f"{mode_prefix}/scene.py", code.encode())
            emit({"type": "llm_output", "index": idx, "mode": mode_key, "stage": "code", "content": code})
            emit({"type": "step", "index": idx, "mode": mode_key,
                  "message": f"[{name}] [{mode_label}] Code: {len(code.splitlines())} lines ({time.monotonic()-_t_mode:.1f}s)"})

            emit({"type": "concept_stage", "index": idx, "stage": "render",
                  "status": "running", "detail": mode_label})
            emit({"type": "step", "index": idx, "mode": mode_key,
                  "message": f"[{name}] [{mode_label}] Rendering…"})
            _t_render = time.monotonic()
            validated = codegen.validate_code(code)
            video_path = renderer.render(validated, store.path(f"{mode_prefix}/render"))
            vid_key = f"{mode_prefix}/video.mp4"
            store.write(vid_key, video_path.read_bytes())
            emit({"type": "concept_stage", "index": idx, "stage": "render", "status": "done"})
            emit({"type": "step", "index": idx, "mode": mode_key,
                  "message": f"[{name}] [{mode_label}] Rendered ({time.monotonic()-_t_render:.1f}s)"})

            if best_code is None:
                best_code = validated
                store.write(f"{prefix}/scene.py", best_code.encode())

            entry: dict = {
                "label": mode_label,
                "video_url": store.url(vid_key),
                "trigger": None,
                "critic_score": None,
                "mode": mode_key,
            }

            if narrator is not None and os.environ.get("OPENAI_API_KEY") and (options or {}).get("voice", True):
                try:
                    vid_path = store.path(vid_key)
                    dur = narrator.get_video_duration(vid_path)
                    sb = storyboard if mode_key in ("two_pass", "dsl") else None
                    script = narrator.generate_script(name, concept.description, sb, dur, shot_list=concept.shot_list)
                    audio_bytes = narrator.generate_tts(script)
                    narrator.merge_audio_video(vid_path, audio_bytes, store.path(vid_key))
                except Exception as exc:
                    emit({"type": "warning", "index": idx, "mode": mode_key, "message": f"[{name}] [{mode_label}] Narration skipped: {exc}"})

            history_entries.append(entry)

        except Exception as exc:
            err_msg = _short_error(str(exc))
            emit({"type": "concept_stage", "index": idx, "stage": "render",
                  "status": "error", "detail": err_msg})
            emit({"type": "step", "index": idx, "mode": mode_key,
                  "message": f"[{name}] [{mode_label}] Failed: {err_msg}"})
            full_err = _actionable_error(str(exc))
            if full_err != err_msg:
                emit({"type": "step", "index": idx, "mode": mode_key,
                      "message": f"[{name}] [{mode_label}] Error detail:\n{full_err}"})
            history_entries.append({
                "label": mode_label,
                "video_url": "",
                "trigger": err_msg,
                "critic_score": None,
                "mode": mode_key,
                "failed": True,
            })

    return best_code, storyboard, history_entries


def _process_concept(
    *,
    job_id: str,
    concept: Concept,
    concept_index: int,
    total: int,
    prefix: str,
    extracted_figures: list[ExtractedFigure],
    codegen: ManimCodeGenerator,
    renderer: ManimRenderer,
    critic: ManimCritic,
    narrator: ManimNarrator,
    store: storage_module.LocalStorage,
    skip_render: bool,
    options: dict | None = None,
    max_retries: int = 3,
    figure_override_index: int | None = None,
    is_regen: bool = False,
) -> None:
    options = options or {}
    emit = lambda ev: runner.emit(job_id, ev)
    name = concept.name
    idx = concept_index
    _t0 = time.monotonic()

    _check(job_id)
    if not is_regen:
        emit({"type": "concept_start", "index": idx, "name": name,
              "message": f"[{idx + 1}/{total}] {name}"})

    # ── RAG retrieval ─────────────────────────────────────────────────────────
    gen_mode: str = options.get("generation_mode", "two_pass")
    gen_modes: list[str] = [m.strip() for m in gen_mode.split(",") if m.strip()] or ["two_pass"]
    is_multi = len(gen_modes) > 1
    single_mode = gen_modes[0]  # used for tagging events in single-mode path

    rag_block = ""
    if options.get("use_rag", True):
        try:
            from src.animation.rag import get_store
            store_rag = get_store()
            if len(store_rag) > 0:
                query = f"{concept.name} {concept.description} {concept.visual_type}"
                examples = store_rag.retrieve(query, k=2)
                rag_block = store_rag.format_for_prompt(examples)
        except Exception as e:
            logger.warning("RAG retrieval failed (best-effort): %s", e)

    # ── Codegen ──────────────────────────────────────────────────────────────
    storyboard: str | None = None
    code: str | None = None
    fig_idx: int | None = None

    def _stage(stage: str, status: str, detail: str = "", **kw):
        emit({"type": "concept_stage", "index": idx, "stage": stage, "status": status,
              "detail": detail, **kw})

    if extracted_figures:
        fig_idx = figure_override_index if figure_override_index is not None \
            else min(idx, len(extracted_figures) - 1)
        try:
            _stage("codegen", "running")
            emit({"type": "step", "index": idx,
                  "message": f"[{name}] Generating code from figure…"})
            code = codegen.generate_from_figure(concept, extracted_figures[fig_idx].image_bytes)
            store.write(f"{prefix}/scene.py", code.encode())
            _stage("codegen", "done")
        except Exception as exc:
            _stage("codegen", "error", detail=_short_error(str(exc)))
            emit({"type": "concept_error", "index": idx, "name": name,
                  "message": f"[{name}] Figure codegen failed: {exc}"})
            _save_concept(job_id, idx, name, concept.visual_type,
                          fig_idx=fig_idx, storyboard=None, video_url=None,
                          critique_md=None, history=[], subtitle_url=None, duration_ms=None,
                          is_regen=is_regen, store=store,
                          extracted_figures=extracted_figures,
                          description=concept.description)
            return
    else:
        # Multi-mode comparison: render each selected mode, show side-by-side
        if is_multi:
            _stage("codegen", "running", detail=f"comparing {len(gen_modes)} modes")
            code, storyboard, compare_history = _generate_multi_mode(
                gen_modes, codegen, concept, rag_block, idx, name, prefix, store, renderer,
                emit, job_id, _check, narrator=narrator, options=options,
            )
            if code is None:
                _stage("codegen", "error", detail="all modes failed to render")
                _save_concept(job_id, idx, name, concept.visual_type,
                              fig_idx=None, storyboard=storyboard, video_url=None,
                              critique_md=None, history=compare_history, subtitle_url=None,
                              duration_ms=int((time.monotonic() - _t0) * 1000),
                              is_regen=is_regen, store=store,
                              extracted_figures=extracted_figures,
                              description=concept.description)
                if not is_regen:
                    emit({"type": "concept_done", "index": idx, "name": name,
                          "message": f"Done: {name}"})
                return
            _stage("done", "done")
            _save_concept(job_id, idx, name, concept.visual_type,
                          fig_idx=None, storyboard=storyboard,
                          video_url=compare_history[0]["video_url"] if compare_history else None,
                          critique_md=None, history=compare_history, subtitle_url=None,
                          duration_ms=int((time.monotonic() - _t0) * 1000),
                          is_regen=is_regen, store=store,
                          extracted_figures=extracted_figures,
                          description=concept.description)
            if not is_regen:
                emit({"type": "concept_done", "index": idx, "name": name,
                      "message": f"Done: {name}"})
            return
        else:
            single_mode = gen_modes[0]
            try:
                _stage("codegen", "running")
                mode_label = {"two_pass": "storyboard + code", "dsl": "DSL spec", "direct": "direct code", "lean": "Lean/Mathlib"}
                emit({"type": "step", "index": idx, "mode": single_mode,
                      "message": f"[{name}] Generating ({mode_label.get(single_mode, single_mode)})…"})
                _t_step = time.monotonic()
                if single_mode == "two_pass":
                    storyboard = codegen.get_storyboard(concept)
                    store.write(f"{prefix}/storyboard.md", storyboard.encode())
                    emit({"type": "llm_output", "index": idx, "mode": single_mode, "stage": "storyboard", "content": storyboard})
                    emit({"type": "step", "index": idx, "mode": single_mode,
                          "message": f"[{name}] Storyboard: {len(storyboard.splitlines())} lines ({time.monotonic()-_t_step:.1f}s) — generating code…"})
                    _t_step = time.monotonic()
                    code = codegen._code_from_storyboard(storyboard, rag_examples=rag_block)
                elif single_mode == "dsl":
                    storyboard = codegen.get_storyboard(concept)
                    store.write(f"{prefix}/storyboard.md", storyboard.encode())
                    emit({"type": "llm_output", "index": idx, "mode": single_mode, "stage": "storyboard", "content": storyboard})
                    emit({"type": "step", "index": idx, "mode": single_mode,
                          "message": f"[{name}] Storyboard: {len(storyboard.splitlines())} lines ({time.monotonic()-_t_step:.1f}s) — compiling DSL…"})
                    _t_step = time.monotonic()
                    code = codegen.generate_dsl(concept, storyboard=storyboard, rag_examples=rag_block)
                else:  # direct / lean
                    code = codegen.generate(concept, mode=single_mode, rag_examples=rag_block)
                store.write(f"{prefix}/scene.py", code.encode())
                emit({"type": "llm_output", "index": idx, "mode": single_mode, "stage": "code", "content": code})
                emit({"type": "step", "index": idx, "mode": single_mode,
                      "message": f"[{name}] Code: {len(code.splitlines())} lines ({time.monotonic()-_t_step:.1f}s)"})
                _stage("codegen", "done")
            except Exception as exc:
                _stage("codegen", "error", detail=_short_error(str(exc)))
                emit({"type": "concept_error", "index": idx, "mode": single_mode, "name": name,
                      "message": f"[{name}] Codegen failed: {exc}"})
                _save_concept(job_id, idx, name, concept.visual_type,
                              fig_idx=None, storyboard=storyboard, video_url=None,
                              critique_md=None, history=[], subtitle_url=None, duration_ms=None,
                              is_regen=is_regen, store=store,
                              extracted_figures=extracted_figures,
                              description=concept.description)
                return

    if skip_render:
        _save_concept(job_id, idx, name, concept.visual_type,
                      fig_idx=fig_idx, storyboard=storyboard, video_url=None,
                      critique_md=None, history=[], subtitle_url=None,
                      duration_ms=int((time.monotonic() - _t0) * 1000),
                      is_regen=is_regen, store=store, extracted_figures=extracted_figures,
                      description=concept.description)
        return

    _check(job_id)
    # ── Pre-render validation ─────────────────────────────────────────────────
    try:
        _stage("validate", "running")
        _t_val = time.monotonic()
        emit({"type": "step", "index": idx, "mode": single_mode, "message": f"[{name}] Validating code…"})
        validated = codegen.validate_code(code)
        if validated != code:
            old_lines, new_lines = len(code.splitlines()), len(validated.splitlines())
            emit({"type": "step", "index": idx, "mode": single_mode,
                  "message": f"[{name}] Validation fixed issues ({old_lines}→{new_lines} lines, {time.monotonic()-_t_val:.1f}s)"})
            code = validated
            store.write(f"{prefix}/scene.py", code.encode())
            emit({"type": "llm_output", "index": idx, "mode": single_mode, "stage": "code", "content": code})
        else:
            emit({"type": "step", "index": idx, "mode": single_mode,
                  "message": f"[{name}] Validation: no issues found ({time.monotonic()-_t_val:.1f}s)"})
        _stage("validate", "done")
    except Exception as exc:
        _stage("validate", "error", detail=_short_error(str(exc)))
        emit({"type": "warning", "index": idx, "mode": single_mode, "message": f"[{name}] Validation skipped: {exc}"})

    # ── Render ───────────────────────────────────────────────────────────────
    video_url: str | None = None
    video_path: Path | None = None
    video_key = f"{prefix}/video.mp4"
    current_code = code
    history: list[dict] = []
    last_error: str | None = None

    seen_hashes: set[str] = {_code_hash(current_code)}
    for attempt in range(1, max_retries + 1):
        try:
            _stage("render", "running", attempt=attempt, max_attempts=max_retries)
            label = f"[{name}] Rendering…" if attempt == 1 \
                else f"[{name}] Rendering (attempt {attempt}/{max_retries})…"
            emit({"type": "step", "index": idx, "mode": single_mode, "message": label})
            _t_render = time.monotonic()
            video_path = renderer.render(current_code, store.path(f"{prefix}/render"))

            attempt_key = f"{prefix}/history/render_{attempt}.mp4"
            video_bytes = video_path.read_bytes()
            store.write(attempt_key, video_bytes)
            store.write(video_key, video_bytes)
            video_url = store.url(video_key)
            entry_label = "Initial render" if attempt == 1 else f"Error fix {attempt - 1}"
            history.append({
                "label": entry_label,
                "video_url": store.url(attempt_key),
                "trigger": _short_error(last_error) if last_error else None,
            })
            last_error = None
            _stage("render", "done", attempt=attempt, max_attempts=max_retries)
            emit({"type": "step", "index": idx, "mode": single_mode,
                  "message": f"[{name}] Render complete ({time.monotonic()-_t_render:.1f}s)"})
            break
        except Exception as exc:
            last_error = str(exc)
            short = _short_error(last_error)
            _stage("render", "error", detail=short, attempt=attempt, max_attempts=max_retries)
            emit({"type": "step", "index": idx, "mode": single_mode,
                  "message": f"[{name}] Render error (attempt {attempt}): {short}"})
            # Emit full traceback into the per-mode log for debugging
            full_err = _actionable_error(last_error)
            if full_err != short:
                emit({"type": "step", "index": idx, "mode": single_mode,
                      "message": f"[{name}] Error detail:\n{full_err}"})
            if attempt < max_retries:
                try:
                    actionable = full_err
                    emit({"type": "step", "index": idx, "mode": single_mode,
                          "message": f"[{name}] Asking LLM to fix error…"})
                    fixed_code = codegen.fix_code(current_code, actionable)
                    new_hash = _code_hash(fixed_code)
                    if new_hash in seen_hashes:
                        emit({"type": "warning",
                              "message": f"[{name}] LLM fix produced identical code — stopping retry"})
                        break
                    seen_hashes.add(new_hash)
                    current_code = fixed_code
                    emit({"type": "llm_output", "index": idx, "mode": single_mode, "stage": "code", "content": fixed_code})
                except Exception:
                    break
            else:
                emit({"type": "warning", "index": idx, "mode": single_mode,
                      "message": f"[{name}] Render failed after {max_retries} attempts: {exc}"})

    _check(job_id)
    # ── Visual diff ───────────────────────────────────────────────────────────
    if video_path and extracted_figures and video_url and fig_idx is not None:
        source_fig = extracted_figures[fig_idx]
        cached_frame: bytes | None = None
        cached_frame_path: object = None  # track which video the frame came from
        for vd in range(1, 3):
            try:
                if video_path is not cached_frame_path:
                    cached_frame = critic.extract_keyframe_bytes(video_path)
                    cached_frame_path = video_path
                frame = cached_frame
                if not frame:
                    break
                emit({"type": "step", "index": idx, "mode": single_mode,
                      "message": f"[{name}] Visual diff pass {vd}…"})
                refined, report = codegen.fix_code_from_visual_diff(
                    current_code, name, source_fig.image_bytes, frame
                )
                store.write(f"{prefix}/visual_diff_{vd}.json", report.encode())
                if refined == current_code:
                    emit({"type": "step", "index": idx, "mode": single_mode,
                          "message": f"[{name}] Visual diff pass {vd}: no changes"})
                    break
                new_vid = renderer.render(refined, store.path(f"{prefix}/render_vd{vd}"))
                vd_key = f"{prefix}/history/vd_{vd}.mp4"
                vd_bytes = new_vid.read_bytes()
                store.write(vd_key, vd_bytes)
                store.write(video_key, vd_bytes)
                video_url = store.url(video_key)
                video_path = new_vid
                current_code = refined
                store.write(f"{prefix}/scene.py", refined.encode())
                history.append({
                    "label": f"Visual diff {vd}",
                    "video_url": store.url(vd_key),
                    "trigger": _diff_trigger(report),
                })
                emit({"type": "step", "index": idx, "mode": single_mode,
                      "message": f"[{name}] Visual diff pass {vd}: re-rendered"})
            except Exception as exc:
                emit({"type": "warning", "index": idx, "mode": single_mode,
                      "message": f"[{name}] Visual diff pass {vd} failed: {exc}"})
                break

    _check(job_id)
    # ── Critic → fix → re-render loop ────────────────────────────────────────
    critique_md: str | None = None
    MAX_CRITIC_ITERS = 3
    best_score: int = 0
    best_code: str = current_code
    best_video_bytes: bytes | None = None
    prev_score: int | None = None  # score that triggered the last fix
    if video_url:
        for crit_iter in range(1, MAX_CRITIC_ITERS + 1):
            _check(job_id)
            try:
                _stage("critic", "running", attempt=crit_iter, max_attempts=MAX_CRITIC_ITERS)
                emit({"type": "step", "index": idx, "mode": single_mode,
                      "message": f"[{name}] Critic pass {crit_iter}/{MAX_CRITIC_ITERS}…"})
                result = critic.critique(
                    video_path=store.path(video_key),
                    concept_name=name,
                    concept_description=concept.description,
                    storyboard=storyboard or "",
                )

                # Regression guard: if fix made things worse, revert to best and stop
                if prev_score is not None and result.score < prev_score:
                    emit({"type": "warning", "index": idx, "mode": single_mode,
                          "message": f"[{name}] Critic fix regressed {prev_score}→{result.score}/10, reverting"})
                    if best_video_bytes is not None:
                        store.write(video_key, best_video_bytes)
                        store.write(f"{prefix}/scene.py", best_code.encode())
                        video_url = store.url(video_key)
                        current_code = best_code
                    break

                # Track best version seen so far
                if result.score > best_score:
                    best_score = result.score
                    best_code = current_code
                    best_video_bytes = store.path(video_key).read_bytes()

                status = "PASS" if result.passes else "FAIL"
                bar = "█" * result.score + "░" * (10 - result.score)
                lines = [f"# Critic Report — {name} (pass {crit_iter})", "",
                         f"**Score:** {result.score}/10  `{bar}`  **{status}**", ""]
                if result.issues:
                    lines += ["## Issues", ""] + [f"- {x}" for x in result.issues] + [""]
                if result.fix_instruction:
                    lines += ["## Fix", "", result.fix_instruction, ""]
                critique_md = "\n".join(lines)
                store.write(f"{prefix}/critique.md", critique_md.encode())
                emit({"type": "llm_output", "index": idx, "mode": single_mode, "stage": "critique", "content": critique_md})
                _stage("critic", "done", attempt=crit_iter, max_attempts=MAX_CRITIC_ITERS, score=result.score)
                emit({"type": "step", "index": idx, "mode": single_mode,
                      "message": f"[{name}] Critic pass {crit_iter}: {result.score}/10 {status}"})

                # Annotate the video this critic just scored
                if history:
                    history[-1]["critic_score"] = result.score

                if result.passes or not result.fix_instruction or crit_iter == MAX_CRITIC_ITERS:
                    break

                # Apply fix and re-render
                _check(job_id)
                emit({"type": "step", "index": idx, "mode": single_mode,
                      "message": f"[{name}] Applying critic fix {crit_iter}…"})
                try:
                    fixed_code = codegen.apply_instruction(current_code, result.fix_instruction)
                except Exception as exc:
                    emit({"type": "warning", "index": idx, "mode": single_mode, "message": f"[{name}] Fix generation failed: {exc}"})
                    break

                try:
                    emit({"type": "step", "index": idx, "mode": single_mode,
                          "message": f"[{name}] Re-rendering (critic fix {crit_iter})…"})
                    new_vid = renderer.render(fixed_code, store.path(f"{prefix}/render_critic{crit_iter}"))
                    critic_vid_key = f"{prefix}/history/critic_{crit_iter}.mp4"
                    critic_bytes = new_vid.read_bytes()
                    store.write(critic_vid_key, critic_bytes)
                    store.write(video_key, critic_bytes)
                    video_url = store.url(video_key)
                    video_path = new_vid
                    prev_score = result.score  # remember score before this fix
                    current_code = fixed_code
                    store.write(f"{prefix}/scene.py", fixed_code.encode())
                    trigger = f"Critic {result.score}/10 — {result.issues[0]}" if result.issues else f"Critic {result.score}/10"
                    history.append({
                        "label": f"Critic fix {crit_iter}",
                        "video_url": store.url(critic_vid_key),
                        "trigger": trigger[:130],
                        "critic_score": None,  # filled in next iteration
                    })
                except Exception as exc:
                    _stage("critic", "error", detail=_short_error(str(exc)), attempt=crit_iter, max_attempts=MAX_CRITIC_ITERS)
                    emit({"type": "warning", "index": idx, "mode": single_mode,
                          "message": f"[{name}] Critic re-render failed: {exc}"})
                    break
            except Exception as exc:
                _stage("critic", "error", detail=_short_error(str(exc)), attempt=crit_iter, max_attempts=MAX_CRITIC_ITERS)
                emit({"type": "warning", "index": idx, "mode": single_mode, "message": f"[{name}] Critic failed: {exc}"})
                break

    # ── Narration ─────────────────────────────────────────────────────────────
    subtitle_url: str | None = None
    if video_url and video_path and os.environ.get("OPENAI_API_KEY") and options.get("voice", True):
        try:
            _stage("narration", "running")
            emit({"type": "step", "index": idx, "mode": single_mode,
                  "message": f"[{name}] Generating narration…"})
            duration = narrator.get_video_duration(video_path)
            script = narrator.generate_script(
                name, concept.description, storyboard, duration, shot_list=concept.shot_list
            )
            audio_bytes = narrator.generate_tts(script)
            narrator.merge_audio_video(video_path, audio_bytes, store.path(video_key))
            video_url = store.url(video_key)
            vtt = narrator.create_vtt(script, duration)
            vtt_key = f"{prefix}/subtitles.vtt"
            store.write(vtt_key, vtt.encode())
            subtitle_url = store.url(vtt_key)

            # Also add the same audio to every history entry so timeline is never silent
            for entry in history:
                hist_url = entry.get("video_url", "")
                if not hist_url:
                    continue
                hist_key = hist_url.removeprefix("/api/files/")
                hist_path = store.path(hist_key)
                if hist_path.exists():
                    try:
                        narrator.merge_audio_video(hist_path, audio_bytes, hist_path)
                    except Exception as e:
                        logger.warning("Failed to add audio to history entry %s: %s", hist_key, e)

            _stage("narration", "done")
            emit({"type": "step", "index": idx, "mode": single_mode,
                  "message": f"[{name}] Narration added"})
        except Exception as exc:
            _stage("narration", "error", detail=_short_error(str(exc)))
            emit({"type": "warning", "index": idx, "mode": single_mode, "message": f"[{name}] Narration skipped: {exc}"})

    _stage("done", "done")
    duration_ms = int((time.monotonic() - _t0) * 1000)
    _save_concept(job_id, idx, name, concept.visual_type,
                  fig_idx=fig_idx, storyboard=storyboard, video_url=video_url,
                  critique_md=critique_md, history=history, subtitle_url=subtitle_url,
                  duration_ms=duration_ms, is_regen=is_regen, store=store,
                  extracted_figures=extracted_figures, description=concept.description)
    if not is_regen:
        emit({"type": "concept_done", "index": idx, "name": name,
              "message": f"Done: {name}"})


def _save_concept(
    job_id: str, idx: int, name: str, visual_type: str,
    fig_idx: int | None, storyboard: str | None, video_url: str | None,
    critique_md: str | None, history: list[dict], subtitle_url: str | None,
    duration_ms: int | None, is_regen: bool, store: storage_module.LocalStorage,
    extracted_figures: list[ExtractedFigure],
    description: str | None = None,
) -> None:
    figure_url: str | None = None
    if extracted_figures and fig_idx is not None:
        fig = extracted_figures[fig_idx]
        figure_url = store.url(f"{job_id}/figures/figure_{fig_idx:02d}_p{fig.page}.png")

    payload = {
        "index": idx, "name": name, "visual_type": visual_type,
        "description": description,
        "figure_url": figure_url, "figure_index": fig_idx,
        "video_url": video_url, "storyboard": storyboard,
        "critique_md": critique_md, "history": history,
        "subtitle_url": subtitle_url,
        "duration_ms": duration_ms,
    }
    if is_regen:
        runner.update_concept(job_id, idx, payload)
    else:
        runner.append_concept(job_id, payload)


# ---------------------------------------------------------------------------
# Novelty detection
# ---------------------------------------------------------------------------

_NOVELTY_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "novelty_detection.txt"


def _detect_novelty(paper_text: str, provider: str, model: str) -> tuple[str, dict]:
    """Run novelty detection. Returns (context_block, parsed_data)."""
    from src.llm_utils import call_llm

    try:
        template = _NOVELTY_PROMPT_PATH.read_text(encoding="utf-8")
        prompt = template.replace("{{PAPER_TEXT}}", paper_text[:6000])
        raw = call_llm(provider, model, prompt, max_tokens=512)

        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if m:
            json_str = m.group(1)
        else:
            fb = re.search(r"\{.*\}", raw, re.DOTALL)
            json_str = fb.group(0) if fb else None

        if not json_str:
            return "", {}

        data = json.loads(json_str)
        contribution = data.get("contribution", "")
        mechanism = data.get("key_mechanism", "")
        limitation = data.get("prior_limitation", "")
        keywords = data.get("focus_keywords", [])

        if not contribution:
            return "", {}

        lines = [
            "## PRIORITY: This Paper's Novel Contribution",
            "",
            f"**What's new:** {contribution}",
        ]
        if mechanism:
            lines.append(f"**Core mechanism to animate:** {mechanism}")
        if limitation:
            lines.append(f"**Prior limitation addressed:** {limitation}")
        if keywords:
            lines.append(f"**Key terms:** {', '.join(keywords)}")
        lines += [
            "",
            "**CRITICAL: Only extract concepts that directly demonstrate this novel contribution and mechanism.**",
            "Skip background material, standard notation, or techniques borrowed unchanged from prior work.",
            "",
            "---",
            "",
        ]
        return "\n".join(lines), {
            "contribution": contribution,
            "key_mechanism": mechanism,
            "prior_limitation": limitation,
            "focus_keywords": keywords,
        }
    except Exception:
        return "", {}


# ---------------------------------------------------------------------------
# Knowledge graph generation
# ---------------------------------------------------------------------------

_GRAPH_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "concept_graph.txt"


def _generate_concept_graph(
    job_id: str,
    concepts: list,
    options: dict,
    store: storage_module.LocalStorage,
    narrator: "ManimNarrator",
    renderer: "ManimRenderer",
) -> None:
    """Generate a concept map animation after all concepts are done."""
    from src.llm_utils import call_llm
    from src.animation.graph_scene import generate_graph_scene

    emit = lambda ev: runner.emit(job_id, ev)
    emit({"type": "stage", "message": "Generating concept map…"})

    provider = os.environ.get("LLM_PROVIDER", "openai")
    model = os.environ.get("LLM_MODEL", os.environ.get("LLM_MODEL", "gpt-4.1"))

    prompt_template = _GRAPH_PROMPT_PATH.read_text(encoding="utf-8")
    concept_list = [
        {"index": i, "name": c.name, "description": c.description, "visual_type": c.visual_type}
        for i, c in enumerate(concepts)
    ]
    prompt = prompt_template.replace("{{CONCEPTS_JSON}}", json.dumps(concept_list, indent=2))

    try:
        raw = call_llm(provider, model, prompt, max_tokens=1024)
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if m:
            json_str = m.group(1)
        else:
            fallback = re.search(r"\{.*\}", raw, re.DOTALL)
            json_str = fallback.group(0) if fallback else None
        edges = json.loads(json_str).get("edges", []) if json_str else []
        runner.update_job(job_id, concept_edges=edges)
    except Exception as exc:
        emit({"type": "warning", "message": f"Concept graph edge detection failed: {exc}"})
        edges = []

    concept_dicts = [
        {"name": c.name, "visual_type": c.visual_type, "description": c.description}
        for c in concepts
    ]
    scene_code = generate_graph_scene(concept_dicts, edges, title="Concept Map")
    if not scene_code:
        return

    graph_prefix = f"{job_id}/graph"
    store.write(f"{graph_prefix}/scene.py", scene_code.encode())

    try:
        video_path = renderer.render(scene_code, store.path(f"{graph_prefix}/render"))
        graph_key = f"{graph_prefix}/video.mp4"
        store.write(graph_key, video_path.read_bytes())
        graph_url = store.url(graph_key)
        runner.update_job(job_id, graph_video_url=graph_url)

        # Narration — describe nodes AND their connections explicitly
        if os.environ.get("OPENAI_API_KEY") and options.get("voice", True):
            try:
                dur = narrator.get_video_duration(video_path)
                names_list = [c.name for c in concepts]

                # Build a connection description from edges
                connection_lines = []
                for e in edges:
                    src_i = int(e.get("from", -1))
                    dst_i = int(e.get("to", -1))
                    rel   = e.get("label", "relates to")
                    if 0 <= src_i < len(concepts) and 0 <= dst_i < len(concepts):
                        connection_lines.append(
                            f"{concepts[src_i].name} {rel} {concepts[dst_i].name}"
                        )

                concept_summary = "; ".join(
                    f"{c.name} ({c.visual_type.replace('_', ' ')})" for c in concepts
                )
                connection_summary = (
                    ". ".join(connection_lines)
                    if connection_lines
                    else "These concepts build on each other to form the paper's core contribution."
                )

                storyboard_hint = (
                    f"Concepts in order: {concept_summary}.\n\n"
                    f"Key relationships: {connection_summary}.\n\n"
                    "For each connection, briefly explain WHY that relationship exists "
                    "and what it means for understanding the paper."
                )

                script = narrator.generate_script(
                    "Concept Map",
                    f"This map shows how {len(concepts)} atomic operations connect: {', '.join(names_list[:5])}.",
                    storyboard_hint,
                    dur,
                )
                audio_bytes = narrator.generate_tts(script)
                narrator.merge_audio_video(video_path, audio_bytes, store.path(graph_key))
            except Exception as e:
                logger.warning("Graph narration failed: %s", e)

        emit({"type": "stage", "message": "Concept map complete"})
    except Exception as exc:
        emit({"type": "warning", "message": f"Concept map render failed: {exc}"})


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------

def run_pipeline(
    job_id: str,
    pdf_key: str,
    options: dict,
    store: storage_module.LocalStorage,
) -> None:
    emit = lambda ev: runner.emit(job_id, ev)

    provider = options.get("llm_provider") or os.environ.get("LLM_PROVIDER", "openai")
    model = options.get("llm_model") or os.environ.get("LLM_MODEL", "gpt-4.1")
    max_concepts: int = options.get("max_concepts", 4)
    figure_context: bool = options.get("figure_context", False)
    skip_render: bool = options.get("skip_render", False)
    parallel_concepts: int = min(int(options.get("parallel_concepts", 4)), _MAX_PARALLEL_WORKERS)

    pdf_path = store.path(pdf_key)

    emit({"type": "stage", "message": "Parsing PDF…"})
    paper = PDFParser().parse(pdf_path)
    emit({"type": "stage", "message": f"Parsed — {len(paper.sections)} sections"})

    extracted_figures: list[ExtractedFigure] = []
    if figure_context:
        emit({"type": "stage", "message": "Extracting figures from PDF…"})
        extracted_figures = FigureExtractor().extract(pdf_path)
        emit({"type": "stage", "message": f"Extracted {len(extracted_figures)} figures"})
        for i, fig in enumerate(extracted_figures):
            fig_key = f"{job_id}/figures/figure_{i:02d}_p{fig.page}.png"
            store.write(fig_key, fig.image_bytes)
            fig_url = store.url(fig_key)
            runner.append_figure(job_id, {"index": i, "url": fig_url, "page": fig.page})
            emit({"type": "figure", "index": i, "url": fig_url, "page": fig.page})

    # ── Novelty / user-hint context ───────────────────────────────────────────
    novelty_context = ""
    user_hint: str = options.get("user_hint", "").strip()

    if options.get("novelty_focus", False):
        emit({"type": "stage", "message": "Detecting novel contribution…"})
        paper_text = "\n\n".join(
            f"{s.title}\n{s.text}" for s in paper.sections[:4]
        )
        novelty_context, novelty_data = _detect_novelty(paper_text, provider, model)
        if novelty_context:
            runner.update_job(job_id, novelty=novelty_data)
            emit({"type": "novelty", "novelty": novelty_data,
                  "message": f"Novel contribution: {novelty_data.get('contribution', '')}"})
            emit({"type": "stage", "message": "Novel contribution identified — steering extraction"})

    if user_hint:
        hint_block = (
            "## User Guidance\n\n"
            f"{user_hint}\n\n"
            "Use this guidance to prioritize which concepts to extract and how to frame them.\n\n"
            "---\n\n"
        )
        novelty_context = hint_block + novelty_context

    emit({"type": "stage", "message": "Extracting concepts…"})
    extractor = ConceptExtractor(provider=provider, model=model)
    all_concepts: list[Concept] = []
    seen: list[str] = []

    for section in paper.sections:
        try:
            for c in extractor.extract(section.to_dict(), novelty_context=novelty_context):
                key = normalize_concept_name(c.name)
                if not any(names_overlap(key, e) for e in seen):
                    seen.append(key)
                    all_concepts.append(c)
        except Exception as exc:
            emit({"type": "warning", "message": f"Extraction failed for '{section.title}': {exc}"})
        if len(all_concepts) >= max_concepts:
            break

    all_concepts = all_concepts[:max_concepts]
    runner.set_raw_concepts(job_id, [c.to_dict() for c in all_concepts])
    stubs = [{"index": i, "name": c.name, "visual_type": c.visual_type, "description": c.description}
             for i, c in enumerate(all_concepts)]
    runner.set_concept_stubs(job_id, stubs)
    emit({
        "type": "concepts_ready",
        "message": f"Found {len(all_concepts)} concepts",
        "concepts": [{"name": c.name, "visual_type": c.visual_type} for c in all_concepts],
    })

    # ── Concept selection gate ────────────────────────────────────────────────
    if options.get("concept_selection", False) and len(all_concepts) > 0:
        _check(job_id)
        runner.set_awaiting_selection(job_id)
        emit({"type": "awaiting_selection",
              "message": "Waiting for concept selection — pick which concepts to animate…"})
        selected_indices = runner.wait_for_selection(job_id, timeout=600)
        _check(job_id)
        if selected_indices is not None:
            all_concepts = [all_concepts[i] for i in selected_indices if i < len(all_concepts)]
            stubs = [{"index": i, "name": c.name, "visual_type": c.visual_type, "description": c.description}
                     for i, c in enumerate(all_concepts)]
            runner.set_concept_stubs(job_id, stubs)
            emit({"type": "stage", "message": f"Animating {len(all_concepts)} selected concepts…"})

    codegen, renderer_obj, critic, narrator_obj = _make_tools(options)
    max_retries: int = max(1, min(10, options.get("max_retries", 3)))

    def process(i: int, concept: Concept) -> None:
        _check(job_id)
        _process_concept(
            job_id=job_id, concept=concept, concept_index=i,
            total=len(all_concepts), prefix=f"{job_id}/concepts/{i:02d}",
            extracted_figures=extracted_figures,
            codegen=codegen, renderer=renderer_obj, critic=critic, narrator=narrator_obj,
            store=store, skip_render=skip_render, options=options, max_retries=max_retries,
        )

    if parallel_concepts <= 1:
        for i, c in enumerate(all_concepts):
            process(i, c)
    else:
        workers = min(parallel_concepts, len(all_concepts))
        emit({"type": "stage",
              "message": f"Processing {len(all_concepts)} concepts ({workers} parallel workers)…"})
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(process, i, c): i for i, c in enumerate(all_concepts)}
            for f in as_completed(futures):
                f.result()

    # Generate concept map after all concepts finish
    if not skip_render and len(all_concepts) >= 2:
        try:
            _check(job_id)
            _generate_concept_graph(job_id, all_concepts, options, store, narrator_obj, renderer_obj)
        except JobCancelledError:
            raise
        except Exception as exc:
            emit({"type": "warning", "message": f"Concept map skipped: {exc}"})


# ---------------------------------------------------------------------------
# Regenerate a single concept with a different figure
# ---------------------------------------------------------------------------

def regenerate_concept(
    job_id: str,
    concept_index: int,
    figure_index: int,
    store: storage_module.LocalStorage,
) -> None:
    emit = lambda ev: runner.emit(job_id, ev)

    raw = runner.get_raw_concept(job_id, concept_index)
    if raw is None:
        emit({"type": "warning", "message": f"No concept data for index {concept_index}"})
        return

    figures = runner.get_figures(job_id)
    if not figures or figure_index >= len(figures):
        emit({"type": "warning", "message": f"Figure index {figure_index} out of range"})
        return

    concept = Concept(
        name=raw["name"],
        description=raw["description"],
        visual_type=raw["visual_type"],
        variables=raw.get("variables", []),
        source_section=raw.get("source_section", ""),
        raw_text=raw.get("raw_text", ""),
        shot_list=raw.get("shot_list", []),
    )

    # Load only the needed figure — avoid reading all figures from disk
    extracted_figures: list[ExtractedFigure] = []
    for i, f in enumerate(figures):
        if i == figure_index:
            key = f["url"].removeprefix("/api/files/")
            path = store.path(key)
            image_bytes = path.read_bytes() if path.exists() else b""
            extracted_figures.append(ExtractedFigure(page=f["page"], image_bytes=image_bytes, width=0, height=0))
        else:
            extracted_figures.append(ExtractedFigure(page=f["page"], image_bytes=b"", width=0, height=0))

    job_state = runner.get_job(job_id)
    options = job_state.options if job_state else {}
    codegen, renderer_obj, critic, narrator_obj = _make_tools(options)
    max_retries: int = max(1, min(10, options.get("max_retries", 3)))

    emit({"type": "step", "index": concept_index,
          "message": f"[{concept.name}] Regenerating with figure {figure_index}…"})

    _process_concept(
        job_id=job_id, concept=concept, concept_index=concept_index,
        total=1, prefix=f"{job_id}/concepts/{concept_index:02d}",
        extracted_figures=extracted_figures,
        codegen=codegen, renderer=renderer_obj, critic=critic, narrator=narrator_obj,
        store=store, skip_render=False, options=options, max_retries=max_retries,
        figure_override_index=figure_index,
        is_regen=True,
    )

    runner.update_concept(job_id, concept_index, {"regen_status": None})
    emit({"type": "concept_done", "index": concept_index, "name": concept.name,
          "message": f"Regenerated: {concept.name}"})
