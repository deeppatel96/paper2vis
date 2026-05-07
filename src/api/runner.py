"""
Job runner.

Runs pipeline jobs in a ThreadPoolExecutor. Progress events are stored as a
list per job so the SSE endpoint can tail them by index (no asyncio bridging
needed — just poll with a cursor).

Cloud upgrade: replace ThreadPoolExecutor with Modal or Celery; keep the
same emit() / get_job() / list_events() interface.
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.api.models import JobState, JobStatus

_executor = ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 2) + 2))
_jobs: dict[str, dict] = {}
_events: dict[str, list[dict]] = {}
_cancelled: set[str] = set()
_lock = threading.Lock()
_data_dir: Path | None = None

# Selection gate — pipeline blocks here until user confirms which concepts to animate
_selection_events: dict[str, threading.Event] = {}
_selected_indices: dict[str, list[int]] = {}


class JobCancelledError(Exception):
    pass


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def init(data_dir: Path) -> None:
    """Call once at startup. Sets the data directory and loads persisted jobs."""
    global _data_dir
    _data_dir = data_dir
    _load_persisted_jobs()


def _state_path(job_id: str) -> Path | None:
    if _data_dir is None:
        return None
    return _data_dir / job_id / "_state.json"


def _persist(job_id: str) -> None:
    path = _state_path(job_id)
    if path is None:
        return
    with _lock:
        data = _jobs.get(job_id)
        if data is None:
            return
        serialized = json.dumps(data, default=str)
    import uuid as _uuid
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"_state_{_uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(serialized, encoding="utf-8")
    tmp.replace(path)


def _load_persisted_jobs() -> None:
    if _data_dir is None:
        return
    for state_file in _data_dir.glob("*/_state.json"):
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            job_id = data.get("job_id")
            if not job_id:
                continue
            # Jobs that were running when the server died show as interrupted
            if data.get("status") in ("running", "queued"):
                data["status"] = JobStatus.failed
                data["error"] = "Server restarted while job was running"
                data["completed_at"] = data.get("completed_at") or datetime.now(timezone.utc).isoformat()
            with _lock:
                _jobs[job_id] = data
                _events[job_id] = []
        except Exception:
            pass  # corrupt state file — skip silently


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_job(job_id: str, pdf_name: str, options: dict) -> JobState:
    with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": JobStatus.queued,
            "pdf_name": pdf_name,
            "options": options,
            "progress": [],
            "concepts": [],
            "concept_stubs": [],
            "figures": [],
            "_raw_concepts": [],
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _events[job_id] = []
    _persist(job_id)
    return JobState(**_jobs[job_id])


def submit_job(job_id: str, fn: Callable, **kwargs: Any) -> None:
    _executor.submit(_run, job_id, fn, kwargs)


def get_job(job_id: str) -> JobState | None:
    with _lock:
        data = _jobs.get(job_id)
    return JobState(**data) if data else None


def list_jobs() -> list[JobState]:
    with _lock:
        jobs = [JobState(**d) for d in _jobs.values()]
    return sorted(jobs, key=lambda j: j.created_at, reverse=True)


def list_events(job_id: str, after: int = 0) -> list[dict]:
    with _lock:
        return _events.get(job_id, [])[after:]


def emit(job_id: str, event: dict) -> None:
    """Thread-safe: append a progress event and mirror text to job.progress."""
    persist = False
    with _lock:
        if job_id not in _events:
            return
        _events[job_id].append(event)
        if msg := event.get("message"):
            _jobs[job_id]["progress"].append(msg)
            persist = True
    if persist:
        _persist(job_id)


def cancel_job(job_id: str) -> bool:
    """Signal a running job to stop. Returns False if not cancellable."""
    with _lock:
        job = _jobs.get(job_id)
        if not job or job["status"] not in (JobStatus.queued, JobStatus.running):
            return False
        _cancelled.add(job_id)
        _jobs[job_id]["status"] = JobStatus.cancelled
        _jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        # Unblock any waiting selection gate so the pipeline thread can exit
        ev = _selection_events.pop(job_id, None)
        _selected_indices.pop(job_id, None)
    if ev is not None:
        ev.set()
    _events.setdefault(job_id, []).append({"type": "cancelled", "message": "Job cancelled"})
    _persist(job_id)
    return True


def is_cancelled(job_id: str) -> bool:
    return job_id in _cancelled


def update_job(job_id: str, **kwargs: Any) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)
            if kwargs.get("status") in ("done", "failed", "cancelled") and not _jobs[job_id].get("completed_at"):
                _jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
    _persist(job_id)


def append_concept(job_id: str, concept: dict) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id]["concepts"].append(concept)
    _persist(job_id)


def update_concept(job_id: str, concept_index: int, updates: dict) -> None:
    """Update fields on an existing concept (matched by index)."""
    with _lock:
        if job_id not in _jobs:
            return
        for c in _jobs[job_id]["concepts"]:
            if c.get("index") == concept_index:
                c.update(updates)
                break
    _persist(job_id)


def append_figure(job_id: str, figure: dict) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id]["figures"].append(figure)
    _persist(job_id)


def set_raw_concepts(job_id: str, concepts_data: list[dict]) -> None:
    """Store full concept data so regeneration can reconstruct Concept objects."""
    with _lock:
        if job_id in _jobs:
            _jobs[job_id]["_raw_concepts"] = concepts_data
    _persist(job_id)


def set_concept_stubs(job_id: str, stubs: list[dict]) -> None:
    """Store lightweight concept stubs so the UI can show skeletons before rendering completes."""
    with _lock:
        if job_id in _jobs:
            _jobs[job_id]["concept_stubs"] = stubs
    _persist(job_id)


def get_raw_concept(job_id: str, index: int) -> dict | None:
    with _lock:
        raw = _jobs.get(job_id, {}).get("_raw_concepts", [])
        if 0 <= index < len(raw):
            return raw[index]
        return None


def get_figures(job_id: str) -> list[dict]:
    with _lock:
        return list(_jobs.get(job_id, {}).get("figures", []))


def set_awaiting_selection(job_id: str) -> None:
    """Mark job as waiting for the user to pick which concepts to animate."""
    ev = threading.Event()
    with _lock:
        _selection_events[job_id] = ev
        if job_id in _jobs:
            _jobs[job_id]["awaiting_selection"] = True
    _persist(job_id)


def resolve_selection(job_id: str, indices: list[int]) -> bool:
    """Called by the API when the user submits their selection. Returns False if no gate exists."""
    with _lock:
        ev = _selection_events.get(job_id)
        if ev is None:
            return False
        _selected_indices[job_id] = indices
        if job_id in _jobs:
            _jobs[job_id]["awaiting_selection"] = False
    ev.set()
    _persist(job_id)
    return True


def wait_for_selection(job_id: str, timeout: float = 600.0) -> list[int] | None:
    """Block the pipeline thread until the user picks concepts (or timeout)."""
    ev = _selection_events.get(job_id)
    if ev is None:
        return None
    ev.wait(timeout=timeout)
    with _lock:
        return _selected_indices.get(job_id)


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _run(job_id: str, fn: Callable, kwargs: dict) -> None:
    if is_cancelled(job_id):
        return
    update_job(job_id, status=JobStatus.running)
    emit(job_id, {"type": "status", "message": "Pipeline started"})
    try:
        fn(job_id=job_id, **kwargs)
        update_job(job_id, status=JobStatus.done)
        emit(job_id, {"type": "done", "message": "Done"})
    except JobCancelledError:
        pass  # status already set to cancelled by cancel_job()
    except Exception as exc:
        update_job(job_id, status=JobStatus.failed, error=str(exc))
        emit(job_id, {"type": "error", "message": str(exc)})
