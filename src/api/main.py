"""
paper2vis FastAPI backend.

Run with:
    uvicorn src.api.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

load_dotenv()

from src.api import runner
from src.api.models import JobState
from src.api.pipeline_adapter import run_pipeline, regenerate_concept
from src.api.storage import LocalStorage

DATA_DIR = Path(__file__).parent.parent.parent / "data"
store = LocalStorage(DATA_DIR)
runner.init(DATA_DIR)

app = FastAPI(title="paper2vis API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@app.post("/api/jobs", response_model=JobState)
async def create_job(
    pdf: UploadFile = File(...),
    max_concepts: int = Form(4),
    quality: str = Form("medium_quality"),
    figure_context: bool = Form(False),
    skip_render: bool = Form(False),
    parallel_concepts: int = Form(1),
    max_retries: int = Form(6),
    voice: bool = Form(True),
    generation_mode: str = Form("two_pass"),
    concept_selection: bool = Form(False),
):
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    job_id = f"{ts}_{uuid.uuid4().hex[:8]}"
    pdf_key = f"{job_id}/upload/{pdf.filename}"
    store.write(pdf_key, await pdf.read())

    valid_modes = {"two_pass", "dsl", "direct", "all"}
    gen_mode = generation_mode if generation_mode in valid_modes else "two_pass"

    tags: list[str] = [gen_mode]
    if figure_context:
        tags.append("figures")
    if voice:
        tags.append("voice")
    if parallel_concepts > 1:
        tags.append(f"{parallel_concepts}×parallel")
    tags.append(quality.replace("_quality", ""))

    options = {
        "max_concepts": max_concepts,
        "quality": quality,
        "figure_context": figure_context,
        "skip_render": skip_render,
        "parallel_concepts": max(1, parallel_concepts),
        "max_retries": max(1, min(10, max_retries)),
        "voice": voice,
        "generation_mode": gen_mode,
        "concept_selection": concept_selection,
        "tags": tags,
    }
    state = runner.create_job(job_id, pdf.filename or "paper.pdf", options)
    runner.submit_job(job_id, run_pipeline, pdf_key=pdf_key, options=options, store=store)
    return state


@app.get("/api/jobs", response_model=list[JobState])
async def list_jobs():
    return runner.list_jobs()


@app.get("/api/jobs/{job_id}", response_model=JobState)
async def get_job(job_id: str):
    state = runner.get_job(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")
    return state


@app.get("/api/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    """SSE endpoint — client polls by cursor to avoid missed events."""
    if not runner.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        cursor = 0
        while True:
            events = runner.list_events(job_id, after=cursor)
            for event in events:
                yield f"data: {json.dumps(event)}\n\n"
                cursor += 1

            job = runner.get_job(job_id)
            if job and job.status in ("done", "failed", "cancelled"):
                # Flush any remaining events then close
                events = runner.list_events(job_id, after=cursor)
                for event in events:
                    yield f"data: {json.dumps(event)}\n\n"
                return

            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# File serving
# ---------------------------------------------------------------------------

@app.get("/api/files/{path:path}")
async def serve_file(path: str):
    file_path = store.path(path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    suffix = file_path.suffix.lower()
    media_types = {
        ".mp4": "video/mp4",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".pdf": "application/pdf",
        ".md": "text/markdown",
        ".py": "text/plain",
        ".vtt": "text/vtt",
    }
    return FileResponse(
        file_path,
        media_type=media_types.get(suffix, "application/octet-stream"),
        headers={"Content-Disposition": "inline"},
    )


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    state = runner.get_job(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")
    if not runner.cancel_job(job_id):
        raise HTTPException(status_code=409, detail=f"Job is not cancellable (status: {state.status})")
    return {"status": "cancelled", "job_id": job_id}


@app.post("/api/jobs/{job_id}/select-concepts")
async def select_concepts(job_id: str, selected_indices: list[int] = Body(..., embed=True)):
    state = runner.get_job(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")
    if not state.awaiting_selection:
        raise HTTPException(status_code=409, detail="Job is not awaiting concept selection")
    if not runner.resolve_selection(job_id, selected_indices):
        raise HTTPException(status_code=409, detail="No selection gate found for this job")
    return {"status": "ok", "selected": selected_indices}


@app.post("/api/jobs/{job_id}/concepts/{concept_index}/regenerate")
async def regenerate_concept_endpoint(
    job_id: str,
    concept_index: int,
    figure_index: int = Body(..., embed=True),
):
    state = runner.get_job(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")
    if not state.figures:
        raise HTTPException(status_code=400, detail="No figures available for this job")
    if figure_index < 0 or figure_index >= len(state.figures):
        raise HTTPException(status_code=400, detail="Figure index out of range")

    # Set job back to running so SSE stream re-opens for progress events
    runner.update_job(job_id, status="running")
    runner.update_concept(job_id, concept_index, {"regen_status": "running"})
    runner.submit_job(
        job_id, regenerate_concept,
        concept_index=concept_index,
        figure_index=figure_index,
        store=store,
    )
    return {"status": "started", "concept_index": concept_index, "figure_index": figure_index}


@app.get("/api/health")
async def health():
    return {"status": "ok"}
