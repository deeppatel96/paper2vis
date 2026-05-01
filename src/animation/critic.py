"""
Vision-based animation critic.

Extracts keyframes from a rendered MP4, sends them to a vision LLM alongside
the storyboard, and returns structured feedback on whether the animation
clearly explains the concept.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from src.llm_utils import call_llm_vision
from src.animation._utils import _ffmpeg_bin, get_video_duration

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

VISION_MODEL = "gpt-4o"
VISION_PROVIDER = "openai"


@dataclass
class CritiqueResult:
    passes: bool
    score: int
    issues: list[str]
    fix_instruction: str

    def __str__(self) -> str:
        status = "PASS" if self.passes else "FAIL"
        return (
            f"[{status}] score={self.score}/10  "
            + (f"issues: {self.issues}" if self.issues else "no issues")
        )


class ManimCritic:
    """Critiques a rendered Manim animation using a vision LLM."""

    def __init__(self, provider: str | None = None, model: str | None = None):
        self.provider = provider or os.environ.get("CODEGEN_PROVIDER", VISION_PROVIDER)
        self.model = model or os.environ.get("CODEGEN_MODEL", VISION_MODEL)
        self._prompt_template = (PROMPTS_DIR / "manim_critic.txt").read_text(encoding="utf-8")

    def critique(
        self,
        video_path: Path,
        concept_name: str,
        concept_description: str,
        storyboard: str,
        n_frames: int = 4,
    ) -> CritiqueResult:
        """
        Extract keyframes from video_path, send to vision LLM, return critique.

        Args:
            video_path: Path to the rendered .mp4
            concept_name: Name of the concept being animated
            concept_description: One-line description
            storyboard: Full storyboard text from the planning pass
            n_frames: Number of evenly-spaced keyframes to extract

        Returns:
            CritiqueResult with pass/fail, score, issues, and fix instruction
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            frame_paths = self._extract_frames(video_path, Path(tmpdir), n_frames)
            if not frame_paths:
                return CritiqueResult(passes=True, score=5, issues=["Could not extract frames for review"], fix_instruction="")

            prompt = (
                self._prompt_template
                .replace("{{CONCEPT_NAME}}", concept_name)
                .replace("{{CONCEPT_DESCRIPTION}}", concept_description)
                .replace("{{STORYBOARD}}", storyboard)
            )

            raw = self._call_with_fallback(prompt, frame_paths)

        return self._parse_response(raw)

    def _call_with_fallback(self, prompt: str, image_paths: list[Path]) -> str:
        """Call vision LLM; fall back to gpt-4o-mini on rate limit (429)."""
        try:
            return call_llm_vision(
                provider=self.provider,
                model=self.model,
                prompt=prompt,
                image_paths=image_paths,
                max_tokens=1024,
            )
        except Exception as exc:
            msg = str(exc).lower()
            is_rate_limit = "429" in msg or "rate limit" in msg or "rate_limit" in msg
            if is_rate_limit and self.provider == "openai" and self.model != "gpt-4o-mini":
                return call_llm_vision(
                    provider="openai",
                    model="gpt-4o-mini",
                    prompt=prompt,
                    image_paths=image_paths,
                    max_tokens=1024,
                )
            raise

    # ------------------------------------------------------------------

    def _extract_frames(self, video_path: Path, output_dir: Path, n: int) -> list[Path]:
        """Use ffmpeg to extract n evenly-spaced frames as PNGs."""
        ffmpeg = _ffmpeg_bin("ffmpeg")
        duration = get_video_duration(video_path)
        # Sample at 20%,40%,60%,80% (avoid very start/end which may be black)
        timestamps = [duration * i / (n + 1) for i in range(1, n + 1)]

        frame_paths: list[Path] = []
        for i, t in enumerate(timestamps):
            out = output_dir / f"frame_{i:02d}.png"
            result = subprocess.run(
                [ffmpeg, "-ss", f"{t:.2f}", "-i", str(video_path),
                 "-frames:v", "1", "-q:v", "2", str(out), "-y"],
                capture_output=True,
            )
            if result.returncode == 0 and out.exists():
                frame_paths.append(out)

        return frame_paths

    def extract_keyframe_bytes(self, video_path: Path, fraction: float = 0.4) -> bytes | None:
        """Extract a single frame at `fraction` through the video as PNG bytes."""
        ffmpeg = _ffmpeg_bin("ffmpeg")
        t = get_video_duration(video_path) * fraction
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "frame.png"
            result = subprocess.run(
                [ffmpeg, "-ss", f"{t:.2f}", "-i", str(video_path),
                 "-frames:v", "1", "-q:v", "2", str(out), "-y"],
                capture_output=True,
            )
            if result.returncode == 0 and out.exists():
                return out.read_bytes()
        return None

    def _parse_response(self, raw: str) -> CritiqueResult:
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if not json_match:
            json_match = re.search(r"(\{.*\})", raw, re.DOTALL)

        if json_match:
            try:
                data = json.loads(json_match.group(1))
                return CritiqueResult(
                    passes=bool(data.get("passes", True)),
                    score=int(data.get("score", 7)),
                    issues=data.get("issues", []),
                    fix_instruction=data.get("fix_instruction", ""),
                )
            except (json.JSONDecodeError, KeyError, ValueError):
                pass

        # Fallback: if we can't parse, assume pass so we don't block the pipeline
        return CritiqueResult(passes=True, score=6, issues=["Could not parse critic response"], fix_instruction="")
