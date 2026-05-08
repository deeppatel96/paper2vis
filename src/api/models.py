from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class FigureInfo(BaseModel):
    index: int
    url: str
    page: int


class VideoHistoryEntry(BaseModel):
    label: str
    video_url: str
    trigger: Optional[str] = None
    critic_score: Optional[int] = None  # score from critic pass that evaluated this version


class ConceptResult(BaseModel):
    index: int
    name: str
    visual_type: str
    description: Optional[str] = None
    figure_url: Optional[str] = None
    figure_index: Optional[int] = None
    video_url: Optional[str] = None
    storyboard: Optional[str] = None
    critique_md: Optional[str] = None
    regen_status: Optional[str] = None   # "running" | None
    history: list[VideoHistoryEntry] = []
    subtitle_url: Optional[str] = None
    duration_ms: Optional[int] = None


class ConceptStub(BaseModel):
    index: int
    name: str
    visual_type: str
    description: Optional[str] = None


class JobState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: str
    status: JobStatus
    pdf_name: str
    options: dict
    progress: list[str] = []
    concepts: list[ConceptResult] = []
    concept_stubs: list[ConceptStub] = []
    figures: list[FigureInfo] = []
    graph_video_url: Optional[str] = None
    concept_edges: list[dict] = []
    awaiting_selection: bool = False
    novelty: Optional[dict] = None
    error: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None


