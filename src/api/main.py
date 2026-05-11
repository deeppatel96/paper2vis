"""
paper2vis FastAPI backend.

Run with:
    uvicorn src.api.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

load_dotenv()
# Also load web/.env.local so CLERK_SECRET_KEY (and other Next.js-only vars) are available
_web_env = Path(__file__).parent.parent.parent / "web" / ".env.local"
if _web_env.exists():
    load_dotenv(_web_env, override=False)

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

VERSION = "1.1.0"

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
        "llm_provider": "openai",
        "llm_model": "gpt-4o-mini",
        "codegen_provider": "anthropic",
        "codegen_model": "claude-sonnet-4-6",
        "max_concepts_limit": 3,
        "quality_limit": "low_quality",
        "jobs_per_month": 5,
    },
    "pro": {
        "llm_provider": "openai",
        "llm_model": "gpt-4o",
        "codegen_provider": "anthropic",
        "codegen_model": "claude-opus-4-6",
        "max_concepts_limit": 16,
        "quality_limit": "medium_quality",
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
        except Exception as e:
            logger.warning("Failed to load tier config, using defaults: %s", e)
    return {tier: dict(cfg) for tier, cfg in _TIER_DEFAULTS.items()}

def _save_tier_configs(configs: dict[str, dict]) -> None:
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_PATH.write_text(json.dumps(configs, indent=2))
    except Exception as e:
        logger.warning("Failed to save tier config: %s", e)

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
    import logging as _logging
    if clerk_id == "dev" or not os.environ.get("SUPABASE_URL"):
        return os.environ.get("DEV_TIER", "pro")
    try:
        sb = _supabase()
        row = sb.table("users").select("tier").eq("clerk_id", clerk_id).maybe_single().execute()
        _logging.info(f"[tier] clerk_id={clerk_id} row={row.data}")
        if row and row.data:
            return row.data.get("tier", "mini")
        # Auto-create user row on first API call (fallback if webhook missed)
        sb.table("users").upsert({"clerk_id": clerk_id, "email": "", "tier": "mini"}).execute()
        return "mini"
    except Exception as e:
        _logging.error(f"[tier] clerk_id={clerk_id} error={e}")
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
    except Exception as e:
        logger.warning("Failed to query usage count: %s", e)
        return 0


def _record_usage(clerk_id: str, job_id: str) -> None:
    if clerk_id == "dev" or not os.environ.get("SUPABASE_URL"):
        return
    try:
        _supabase().table("usage").insert({"clerk_id": clerk_id, "job_id": job_id}).execute()
    except Exception as e:
        logger.warning("Failed to record usage for %s/%s: %s", clerk_id, job_id, e)


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
    critic_model_override: str = Form(""),
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
    pdf_bytes = await pdf.read()
    store.write(pdf_key, pdf_bytes)
    # Mirror PDF to Supabase Storage so it's accessible when debugging prod jobs locally
    if os.environ.get("SUPABASE_URL"):
        sb = _supabase()
        try:
            sb.storage.from_("pdfs").upload(pdf_key, pdf_bytes, {"content-type": "application/pdf", "upsert": "true"})
        except Exception as e:
            logger.warning("Failed to mirror PDF to Supabase Storage: %s", e)

    valid_modes = {"two_pass", "dsl", "direct", "lean"}
    requested = [m.strip() for m in generation_mode.split(",") if m.strip()]
    filtered = [m for m in requested if m in valid_modes]
    gen_mode = ",".join(filtered) if filtered else "two_pass"

    tags: list[str] = [gen_mode, tier, f"v{VERSION}"]
    if figure_context:
        tags.append("figures")
    if voice:
        tags.append("voice")
    if parallel_concepts > 1:
        tags.append(f"{parallel_concepts}×parallel")
    tags.append(quality.replace("_quality", ""))
    if novelty_focus:
        tags.append("novelty")
    if use_rag:
        tags.append("rag")
    if concept_selection:
        tags.append("concept-pick")
    llm_tag = llm_model_override or cfg["llm_model"]
    codegen_tag = codegen_model_override or cfg["codegen_model"]
    if llm_tag:
        tags.append(f"ext:{llm_tag}")
    if codegen_tag:
        tags.append(f"gen:{codegen_tag}")

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
        "critic_provider": _infer_provider(critic_model_override, cfg["codegen_provider"]),
        "critic_model": critic_model_override or codegen_model_override or cfg["codegen_model"],
    }
    state = runner.create_job(job_id, pdf.filename or "paper.pdf", options, clerk_id=clerk_id)
    _record_usage(clerk_id, job_id)
    runner.submit_job(job_id, run_pipeline, pdf_key=pdf_key, options=options, store=store)
    return state


@app.get("/api/version")
async def get_version():
    return {"version": VERSION}


@app.get("/api/jobs", response_model=list[JobState])
async def list_jobs(clerk_id: str = Depends(verify_token)):
    return runner.list_jobs(clerk_id=clerk_id)


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
        terminal_sent = False
        while True:
            events = runner.list_events(job_id, after=cursor)
            for event in events:
                yield f"data: {json.dumps(event)}\n\n"
                cursor += 1
                if event.get("type") in ("done", "error", "cancelled"):
                    terminal_sent = True

            job = runner.get_job(job_id)
            if job and job.status in ("done", "failed", "cancelled"):
                # Drain any remaining events
                events = runner.list_events(job_id, after=cursor)
                for event in events:
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("type") in ("done", "error", "cancelled"):
                        terminal_sent = True
                # Ensure client always gets a terminal event to close cleanly
                if not terminal_sent:
                    terminal_type = "error" if job.status == "failed" else job.status
                    yield f"data: {json.dumps({'type': terminal_type})}\n\n"
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
        # Fall back to Supabase Storage for production files not on this machine
        if os.environ.get("SUPABASE_URL") and path.endswith(".pdf"):
            sb = _supabase()
            try:
                signed = sb.storage.from_("pdfs").create_signed_url(path, 300)
                signed_url = signed.get("signedURL") or signed.get("signed_url") or (signed.get("data") or {}).get("signedUrl")
                if signed_url:
                    return RedirectResponse(signed_url)
            except Exception:
                pass
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

@app.post("/api/jobs/{job_id}/clone", response_model=JobState)
async def clone_job(job_id: str, clerk_id: str = Depends(verify_token)):
    """Re-submit a job with the same PDF and options. Useful for re-running after config changes."""
    state = runner.get_job(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")

    # Enforce monthly limit for the cloning user
    tier = _get_user_tier(clerk_id)
    cfg = TIER_CONFIGS.get(tier, TIER_CONFIGS["mini"])
    used = _get_monthly_usage(clerk_id)
    if used >= cfg["jobs_per_month"]:
        raise HTTPException(status_code=429, detail=f"Monthly limit reached ({used}/{cfg['jobs_per_month']} jobs).")

    # Locate the original PDF in storage
    pdf_key = f"{job_id}/upload/{state.pdf_name}"
    pdf_path = store.path(pdf_key)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Original PDF not found in storage.")
    pdf_bytes = pdf_path.read_bytes()

    # Build options from the original job, applying current tier caps
    orig = dict(state.options)
    quality_order = ["low_quality", "medium_quality", "high_quality"]
    tier_q = quality_order.index(cfg["quality_limit"])
    req_q = quality_order.index(orig.get("quality", "medium_quality")) if orig.get("quality") in quality_order else 0
    quality = quality_order[min(req_q, tier_q)]

    # Stamp with new version tag so you can tell runs apart
    tags: list[str] = [t for t in (orig.get("tags") or []) if not t.startswith("v")]
    tags.append(f"v{VERSION}")
    tags.append("clone")

    options = {**orig, "quality": quality, "tags": tags,
               "max_concepts": min(orig.get("max_concepts", 4), cfg["max_concepts_limit"])}

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    new_id = f"{ts}_{uuid.uuid4().hex[:8]}"
    new_pdf_key = f"{new_id}/upload/{state.pdf_name}"
    store.write(new_pdf_key, pdf_bytes)

    new_state = runner.create_job(new_id, state.pdf_name, options, clerk_id=clerk_id)
    _record_usage(clerk_id, new_id)
    runner.submit_job(new_id, run_pipeline, pdf_key=new_pdf_key, options=options, store=store)
    return new_state


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
    # Upsert user first — invite_codes.used_by has a FK to users.clerk_id
    sb.table("users").upsert({"clerk_id": clerk_id, "email": "", "tier": "pro"}).execute()
    sb.table("invite_codes").update({
        "used_by": clerk_id,
        "used_at": datetime.now(timezone.utc).isoformat(),
    }).eq("code", code).execute()
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
async def get_config(clerk_id: str = Depends(verify_token)):
    return TIER_CONFIGS


@app.post("/api/admin/config")
async def save_config(
    config: dict = Body(...),
    clerk_id: str = Depends(verify_token),
):
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


def _estimate_cost(options: dict, concept_count: int) -> float:
    """Rough LLM + TTS cost estimate in USD. Mirrors Dashboard.tsx estConceptCost logic."""
    PRICING: dict[str, tuple[float, float]] = {  # ($/MTok_in, $/MTok_out)
        "claude-haiku-4-5": (0.80, 4.0),
        "claude-haiku-4-5-20251001": (0.80, 4.0),
        "claude-sonnet-4-6": (3.0, 15.0),
        "claude-opus-4-6": (15.0, 75.0),
        "gpt-4o": (2.5, 10.0),
        "gpt-4o-mini": (0.15, 0.60),
    }

    def _cost(model: str, in_tok: int, out_tok: int) -> float:
        p = PRICING.get(model, (3.0, 15.0))
        return (in_tok * p[0] + out_tok * p[1]) / 1_000_000

    llm = options.get("llm_model_override") or options.get("llm_model") or "gpt-4o"
    codegen = options.get("codegen_model_override") or options.get("codegen_model") or "claude-sonnet-4-6"
    n = max(concept_count, 1)
    gen_mode = options.get("generation_mode", "two_pass")
    modes = len(gen_mode.split(",")) if gen_mode else 1
    max_retries = int(options.get("max_retries", 6))

    # Extraction (once per job): validate + concept list
    total = _cost(llm, 4000, 800)
    for _ in range(n):
        # Storyboard + codegen (per mode)
        total += _cost(codegen, 1000 + 1500, 400 + 750) * modes
        # Assume half of max_retries used on average for fix_code calls
        total += _cost(codegen, 2000, 750) * (max_retries // 2)
        # Critic base + one fix pass
        total += _cost(codegen, 750 + 2000, 250 + 750)
        # Narration script + TTS
        if options.get("voice"):
            total += _cost(codegen, 2000, 300)
            total += 500 * 15 / 1_000_000
    return round(total, 4)


def _clerk_emails(clerk_ids: list[str]) -> dict[str, str]:
    """Fetch emails for a list of Clerk user IDs via the Clerk REST API.

    Returns a dict {clerk_id: email}. Silently returns empty dict if
    CLERK_SECRET_KEY is not configured or the request fails.
    """
    secret = os.environ.get("CLERK_SECRET_KEY", "")
    if not secret or not clerk_ids:
        return {}
    try:
        import requests as _requests
        batch_size = 100
        result: dict[str, str] = {}
        for i in range(0, len(clerk_ids), batch_size):
            batch = clerk_ids[i : i + batch_size]
            params = [("user_id[]", cid) for cid in batch] + [("limit", batch_size)]
            resp = _requests.get(
                "https://api.clerk.com/v1/users",
                params=params,
                headers={"Authorization": f"Bearer {secret}"},
                timeout=5,
            )
            resp.raise_for_status()
            for u in resp.json():
                emails = u.get("email_addresses") or []
                primary_id = u.get("primary_email_address_id")
                email = ""
                for e in emails:
                    if e.get("id") == primary_id:
                        email = e.get("email_address", "")
                        break
                if not email and emails:
                    email = emails[0].get("email_address", "")
                if email:
                    result[u["id"]] = email
        return result
    except Exception as exc:
        logger.warning("Clerk email fetch failed: %s", exc)
        return {}


@app.get("/api/admin/users")
async def list_all_users(
    x_admin_secret: str = Header(default="", alias="x-admin-secret"),
):
    """List all users with tier and job count."""
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    if not admin_secret or x_admin_secret != admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not os.environ.get("SUPABASE_URL"):
        # Local dev: derive users from in-memory jobs
        all_jobs = runner.list_jobs()
        from collections import Counter
        counts: Counter = Counter()
        earliest: dict = {}
        costs: dict = {}
        for job in all_jobs:
            cid = getattr(job, "_clerk_id", "") or "dev"
            counts[cid] += 1
            ca = getattr(job, "created_at", None) or ""
            if cid not in earliest or ca < earliest[cid]:
                earliest[cid] = ca
            costs[cid] = costs.get(cid, 0.0) + _estimate_cost(job.options or {}, len(job.concepts))
        return [
            {"clerk_id": cid, "tier": os.environ.get("DEV_TIER", "pro"), "created_at": earliest.get(cid, ""), "job_count": cnt, "email": None, "estimated_cost_usd": round(costs.get(cid, 0.0), 4)}
            for cid, cnt in counts.most_common()
        ]
    users = _supabase().table("users").select("*").order("created_at", desc=True).execute()
    user_rows = users.data or []
    if user_rows:
        ids = [u["clerk_id"] for u in user_rows]
        jobs = _supabase().table("jobs").select("clerk_id, status, state").in_("clerk_id", ids).execute()
        from collections import Counter
        counts = Counter(j["clerk_id"] for j in (jobs.data or []))
        costs_map: dict = {}
        for j in (jobs.data or []):
            raw = j.get("state") or {}
            state = json.loads(raw) if isinstance(raw, str) else raw
            cid = j["clerk_id"]
            costs_map[cid] = costs_map.get(cid, 0.0) + _estimate_cost(state.get("options", {}), len(state.get("concepts", [])))
        # Enrich missing emails from Clerk API (covers Google OAuth + any users
        # whose webhook fired before the email column existed)
        missing_email_ids = [u["clerk_id"] for u in user_rows if not u.get("email")]
        clerk_email_map = _clerk_emails(missing_email_ids)
        for u in user_rows:
            u["job_count"] = counts.get(u["clerk_id"], 0)
            u["estimated_cost_usd"] = round(costs_map.get(u["clerk_id"], 0.0), 4)
            if not u.get("email") and u["clerk_id"] in clerk_email_map:
                u["email"] = clerk_email_map[u["clerk_id"]]
                # Backfill to Supabase so next load is instant
                try:
                    _supabase().table("users").update({"email": u["email"]}).eq("clerk_id", u["clerk_id"]).execute()
                except Exception:
                    pass
    return user_rows


@app.get("/api/admin/users/{clerk_id}/jobs")
async def list_user_jobs(
    clerk_id: str,
    x_admin_secret: str = Header(default="", alias="x-admin-secret"),
):
    """List all jobs for a specific user (admin view)."""
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    if not admin_secret or x_admin_secret != admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not os.environ.get("SUPABASE_URL"):
        # Local dev: read from in-memory runner (clerk_id "dev" = all jobs)
        all_jobs = runner.list_jobs(clerk_id=None if clerk_id == "dev" else clerk_id)
        return [
            {
                "job_id": job.job_id,
                "pdf_name": job.pdf_name,
                "status": job.status,
                "created_at": job.created_at,
                "completed_at": job.completed_at,
                "options": job.options,
                "concept_count": len(job.concepts),
            }
            for job in sorted(all_jobs, key=lambda j: j.created_at or "", reverse=True)
        ]
    rows = _supabase().table("jobs").select("job_id, pdf_name, status, created_at, completed_at, state").eq("clerk_id", clerk_id).order("created_at", desc=True).execute()
    results = []
    for row in (rows.data or []):
        raw = row.get("state") or {}
        state = json.loads(raw) if isinstance(raw, str) else raw
        results.append({
            "job_id": row["job_id"],
            "pdf_name": row["pdf_name"],
            "status": row["status"],
            "created_at": row["created_at"],
            "completed_at": row.get("completed_at"),
            "options": state.get("options", {}),
            "concept_count": len(state.get("concepts", [])),
        })
    return results


@app.get("/api/admin/jobs")
async def list_all_jobs(
    request: Request,
    x_admin_secret: str = Header(default="", alias="x-admin-secret"),
):
    """List all jobs across all users (admin or pro-tier JWT)."""
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    is_admin = bool(admin_secret and x_admin_secret == admin_secret)
    deny_reason = "no valid auth"
    if not is_admin:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header:
            deny_reason = "no Authorization header"
        else:
            try:
                clerk_id = verify_token(authorization=auth_header)
                tier = _get_user_tier(clerk_id)
                if tier == "pro":
                    is_admin = True
                else:
                    deny_reason = f"tier is '{tier}', not 'pro'"
            except Exception as e:
                deny_reason = f"token error: {e}"
    if not is_admin:
        raise HTTPException(status_code=403, detail=f"Forbidden: {deny_reason}")
    if not os.environ.get("SUPABASE_URL"):
        all_jobs = runner.list_jobs(clerk_id=None)
        return [
            {
                "job_id": job.job_id,
                "pdf_name": job.pdf_name,
                "status": job.status,
                "created_at": job.created_at,
                "completed_at": job.completed_at,
                "options": job.options,
                "concept_count": len(job.concepts),
            }
            for job in sorted(all_jobs, key=lambda j: j.created_at or "", reverse=True)
        ]
    rows = _supabase().table("jobs").select("job_id, pdf_name, status, created_at, completed_at, state").order("created_at", desc=True).limit(500).execute()
    results = []
    for row in (rows.data or []):
        raw = row.get("state") or {}
        state = json.loads(raw) if isinstance(raw, str) else raw
        results.append({
            "job_id": row["job_id"],
            "pdf_name": row["pdf_name"],
            "status": row["status"],
            "created_at": row["created_at"],
            "completed_at": row.get("completed_at"),
            "options": state.get("options", {}),
            "concept_count": len(state.get("concepts", [])),
        })
    return results


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
