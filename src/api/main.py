"""
paper2vis FastAPI backend.

Run with:
    uvicorn src.api.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

load_dotenv()

from src.api import runner
from src.api.auth import verify_token
from src.api.models import JobState
from src.api.pipeline_adapter import run_pipeline, regenerate_concept
from src.api.storage import LocalStorage
from src.api.webhooks import handle_clerk_webhook

DATA_DIR = Path(__file__).parent.parent.parent / "data"
store = LocalStorage(DATA_DIR)
runner.init(DATA_DIR)

app = FastAPI(title="paper2vis API")

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Tier configuration (mutable — overridable via /api/admin/config)
# ---------------------------------------------------------------------------

_CONFIG_PATH = DATA_DIR / "tier_config.json"

_TIER_DEFAULTS: dict[str, dict] = {
    "mini": {
        "llm_provider": "anthropic",
        "llm_model": "claude-haiku-4-5-20251001",
        "codegen_provider": "anthropic",
        "codegen_model": "claude-sonnet-4-6",
        "max_concepts_limit": 3,
        "quality_limit": "low_quality",
        "jobs_per_month": 5,
    },
    "pro": {
        "llm_provider": "anthropic",
        "llm_model": "claude-sonnet-4-6",
        "codegen_provider": "anthropic",
        "codegen_model": "claude-opus-4-6",
        "max_concepts_limit": 16,
        "quality_limit": "high_quality",
        "jobs_per_month": 50,
    },
}

def _infer_provider(model: str, default: str) -> str:
    if not model:
        return default
    if model.startswith("claude-"):
        return "anthropic"
    if model.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    return default


def _load_tier_configs() -> dict[str, dict]:
    if _CONFIG_PATH.exists():
        try:
            saved = json.loads(_CONFIG_PATH.read_text())
            merged = {tier: {**_TIER_DEFAULTS[tier], **saved.get(tier, {})} for tier in _TIER_DEFAULTS}
            return merged
        except Exception:
            pass
    return {tier: dict(cfg) for tier, cfg in _TIER_DEFAULTS.items()}

def _save_tier_configs(configs: dict[str, dict]) -> None:
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_PATH.write_text(json.dumps(configs, indent=2))
    except Exception:
        pass

TIER_CONFIGS: dict[str, dict] = _load_tier_configs()

# ---------------------------------------------------------------------------
# Supabase helpers (gracefully no-op when not configured)
# ---------------------------------------------------------------------------

def _supabase():
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


def _get_user_tier(clerk_id: str) -> str:
    """Return the user's tier from Supabase. Defaults to 'mini' on any failure."""
    if clerk_id == "dev" or not os.environ.get("SUPABASE_URL"):
        return os.environ.get("DEV_TIER", "pro")
    try:
        sb = _supabase()
        row = sb.table("users").select("tier").eq("clerk_id", clerk_id).maybe_single().execute()
        if row and row.data:
            return row.data.get("tier", "mini")
        # Auto-create user row on first API call (fallback if webhook missed)
        sb.table("users").upsert({"clerk_id": clerk_id, "email": "", "tier": "mini"}).execute()
        return "mini"
    except Exception:
        return "mini"


def _get_monthly_usage(clerk_id: str) -> int:
    """Count jobs created by this user in the current calendar month."""
    if clerk_id == "dev" or not os.environ.get("SUPABASE_URL"):
        return 0
    try:
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        sb = _supabase()
        result = (
            sb.table("usage")
            .select("id", count="exact")
            .eq("clerk_id", clerk_id)
            .gte("created_at", month_start)
            .execute()
        )
        return result.count or 0
    except Exception:
        return 0


def _record_usage(clerk_id: str, job_id: str) -> None:
    if clerk_id == "dev" or not os.environ.get("SUPABASE_URL"):
        return
    try:
        _supabase().table("usage").insert({"clerk_id": clerk_id, "job_id": job_id}).execute()
    except Exception:
        pass  # Non-fatal — job still runs


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
    use_rag: bool = Form(True),
    novelty_focus: bool = Form(False),
    user_hint: str = Form(""),
    llm_model_override: str = Form(""),
    codegen_model_override: str = Form(""),
    clerk_id: str = Depends(verify_token),
):
    tier = _get_user_tier(clerk_id)
    cfg = TIER_CONFIGS.get(tier, TIER_CONFIGS["mini"])

    # Enforce monthly job limit
    used = _get_monthly_usage(clerk_id)
    limit = cfg["jobs_per_month"]
    if used >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Monthly limit reached ({used}/{limit} jobs). Upgrade to Pro for more.",
        )

    # Cap options to tier maximums
    max_concepts = min(max_concepts, cfg["max_concepts_limit"])
    quality_order = ["low_quality", "medium_quality", "high_quality"]
    tier_quality_idx = quality_order.index(cfg["quality_limit"])
    req_quality_idx = quality_order.index(quality) if quality in quality_order else 0
    quality = quality_order[min(req_quality_idx, tier_quality_idx)]

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    job_id = f"{ts}_{uuid.uuid4().hex[:8]}"
    pdf_key = f"{job_id}/upload/{pdf.filename}"
    store.write(pdf_key, await pdf.read())

    valid_modes = {"two_pass", "dsl", "direct", "all"}
    gen_mode = generation_mode if generation_mode in valid_modes else "two_pass"

    tags: list[str] = [gen_mode, tier]
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
        "use_rag": use_rag,
        "novelty_focus": novelty_focus,
        "user_hint": user_hint,
        "tags": tags,
        # Tier-specific model config — user override takes precedence over tier defaults
        "llm_provider": _infer_provider(llm_model_override, cfg["llm_provider"]),
        "llm_model": llm_model_override or cfg["llm_model"],
        "codegen_provider": _infer_provider(codegen_model_override, cfg["codegen_provider"]),
        "codegen_model": codegen_model_override or cfg["codegen_model"],
    }
    state = runner.create_job(job_id, pdf.filename or "paper.pdf", options)
    _record_usage(clerk_id, job_id)
    runner.submit_job(job_id, run_pipeline, pdf_key=pdf_key, options=options, store=store)
    return state


@app.get("/api/jobs", response_model=list[JobState])
async def list_jobs(clerk_id: str = Depends(verify_token)):
    return runner.list_jobs()


@app.get("/api/jobs/{job_id}", response_model=JobState)
async def get_job(job_id: str, clerk_id: str = Depends(verify_token)):
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


# ---------------------------------------------------------------------------
# Job control
# ---------------------------------------------------------------------------

@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, clerk_id: str = Depends(verify_token)):
    state = runner.get_job(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")
    if not runner.cancel_job(job_id):
        raise HTTPException(status_code=409, detail=f"Job is not cancellable (status: {state.status})")
    return {"status": "cancelled", "job_id": job_id}


@app.post("/api/jobs/{job_id}/select-concepts")
async def select_concepts(
    job_id: str,
    selected_indices: list[int] = Body(..., embed=True),
    clerk_id: str = Depends(verify_token),
):
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
    clerk_id: str = Depends(verify_token),
):
    state = runner.get_job(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")
    if not state.figures:
        raise HTTPException(status_code=400, detail="No figures available for this job")
    if figure_index < 0 or figure_index >= len(state.figures):
        raise HTTPException(status_code=400, detail="Figure index out of range")

    runner.update_job(job_id, status="running")
    runner.update_concept(job_id, concept_index, {"regen_status": "running"})
    runner.submit_job(
        job_id, regenerate_concept,
        concept_index=concept_index,
        figure_index=figure_index,
        store=store,
    )
    return {"status": "started", "concept_index": concept_index, "figure_index": figure_index}


# ---------------------------------------------------------------------------
# Usage / profile
# ---------------------------------------------------------------------------

@app.get("/api/me/usage")
async def get_my_usage(clerk_id: str = Depends(verify_token)):
    tier = _get_user_tier(clerk_id)
    cfg = TIER_CONFIGS.get(tier, TIER_CONFIGS["mini"])
    used = _get_monthly_usage(clerk_id)
    now = datetime.now(timezone.utc)
    # Reset date = 1st of next month
    if now.month == 12:
        reset = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        reset = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return {
        "clerk_id": clerk_id,
        "tier": tier,
        "jobs_used": used,
        "jobs_limit": cfg["jobs_per_month"],
        "reset_date": reset.isoformat(),
    }


# ---------------------------------------------------------------------------
# Invite codes — self-service Pro upgrade
# ---------------------------------------------------------------------------

@app.post("/api/invite")
async def redeem_invite(
    code: str = Body(..., embed=True),
    clerk_id: str = Depends(verify_token),
):
    """Redeem a single-use invite code to upgrade the calling user to Pro."""
    if not os.environ.get("SUPABASE_URL"):
        raise HTTPException(status_code=503, detail="Supabase not configured")
    sb = _supabase()
    row = sb.table("invite_codes").select("*").eq("code", code).maybe_single().execute()
    if not row.data:
        raise HTTPException(status_code=400, detail="Invalid invite code")
    if row.data.get("used_by"):
        raise HTTPException(status_code=400, detail="Invite code already used")
    from datetime import datetime, timezone
    sb.table("invite_codes").update({
        "used_by": clerk_id,
        "used_at": datetime.now(timezone.utc).isoformat(),
    }).eq("code", code).execute()
    sb.table("users").upsert({"clerk_id": clerk_id, "tier": "pro"}).execute()
    return {"status": "ok", "tier": "pro"}


# ---------------------------------------------------------------------------
# Admin — manual tier management + invite code generation
# ---------------------------------------------------------------------------

@app.post("/api/admin/invite-codes")
async def create_invite_code(
    note: str = Body(default="", embed=True),
    x_admin_secret: str = Header(default="", alias="x-admin-secret"),
):
    """Generate a single-use Pro invite code. Optionally label it with a recipient name."""
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    if not admin_secret or x_admin_secret != admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not os.environ.get("SUPABASE_URL"):
        raise HTTPException(status_code=503, detail="Supabase not configured")
    code = uuid.uuid4().hex[:12]
    _supabase().table("invite_codes").insert({"code": code, "note": note}).execute()
    return {"code": code, "note": note}


@app.get("/api/admin/invite-codes")
async def list_invite_codes(
    x_admin_secret: str = Header(default="", alias="x-admin-secret"),
):
    """List all invite codes and their redemption status."""
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    if not admin_secret or x_admin_secret != admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not os.environ.get("SUPABASE_URL"):
        raise HTTPException(status_code=503, detail="Supabase not configured")
    rows = _supabase().table("invite_codes").select("*").order("created_at", desc=True).execute()
    return rows.data

@app.get("/api/admin/config")
async def get_config(
    x_admin_secret: str = Header(default="", alias="x-admin-secret"),
):
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    if not admin_secret or x_admin_secret != admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    return TIER_CONFIGS


@app.post("/api/admin/config")
async def save_config(
    config: dict = Body(...),
    x_admin_secret: str = Header(default="", alias="x-admin-secret"),
):
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    if not admin_secret or x_admin_secret != admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    valid_tiers = {"mini", "pro"}
    valid_keys = {"llm_provider", "llm_model", "codegen_provider", "codegen_model",
                  "max_concepts_limit", "quality_limit", "jobs_per_month"}
    for tier, values in config.items():
        if tier not in valid_tiers:
            raise HTTPException(status_code=400, detail=f"Unknown tier: {tier}")
        if not isinstance(values, dict):
            raise HTTPException(status_code=400, detail=f"Invalid config for tier: {tier}")
        unknown = set(values.keys()) - valid_keys
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown config keys: {unknown}")
        TIER_CONFIGS[tier].update(values)
    _save_tier_configs(TIER_CONFIGS)
    return TIER_CONFIGS


@app.post("/api/admin/users/{clerk_id}/tier")
async def set_user_tier(
    clerk_id: str,
    tier: str = Body(..., embed=True),
    x_admin_secret: str = Header(default="", alias="x-admin-secret"),
):
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    if not admin_secret or x_admin_secret != admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    if tier not in ("mini", "pro"):
        raise HTTPException(status_code=400, detail="tier must be 'mini' or 'pro'")
    if not os.environ.get("SUPABASE_URL"):
        raise HTTPException(status_code=503, detail="Supabase not configured")
    _supabase().table("users").upsert({"clerk_id": clerk_id, "tier": tier}).execute()
    return {"clerk_id": clerk_id, "tier": tier}


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

@app.post("/api/webhooks/clerk")
async def clerk_webhook(
    request: Request,
    svix_id: str = Header(default="", alias="svix-id"),
    svix_timestamp: str = Header(default="", alias="svix-timestamp"),
    svix_signature: str = Header(default="", alias="svix-signature"),
):
    return await handle_clerk_webhook(request, svix_id, svix_timestamp, svix_signature)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok"}
