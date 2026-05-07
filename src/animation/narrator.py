"""
Narration: concept → script → TTS audio → merge with video → WebVTT subtitles.

Only works with OpenAI provider (TTS API). Gracefully skipped for others.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from src.animation._utils import _ffmpeg_bin, get_video_duration as _get_video_duration


class ManimNarrator:
    def __init__(self, provider: str = "openai", model: str | None = None):
        self.provider = provider
        self.model = model or os.environ.get("LLM_MODEL", "gpt-4.1")

    # ------------------------------------------------------------------

    def generate_script(
        self,
        concept_name: str,
        concept_description: str,
        storyboard: str | None,
        video_duration: float,
        shot_list: list[str] | None = None,
    ) -> str:
        """Ask the LLM to write a narration for a video of the given duration."""
        from src.llm_utils import call_llm

        target_words = int(video_duration * 130 / 60)  # ~130 wpm

        # Prefer concise shot list over full storyboard for beat context
        if shot_list:
            beats_text = "\n".join(f"{i+1}. {b}" for i, b in enumerate(shot_list))
            beat_section = f"\nWhat happens on screen (beat by beat):\n{beats_text}"
        elif storyboard:
            # Trim to first 600 chars to avoid overwhelming the narration prompt
            trimmed = storyboard[:600].rsplit("\n", 1)[0]
            beat_section = f"\nAnimation summary:\n{trimmed}"
        else:
            beat_section = ""

        prompt = (
            f"Write a clear, engaging narration for a {video_duration:.0f}-second "
            f"educational animation about: {concept_name}.\n\n"
            f"Concept description: {concept_description}{beat_section}\n\n"
            f"Requirements:\n"
            f"- Target ~{target_words} words (fits {video_duration:.0f}s at 130 wpm)\n"
            f"- Plain prose only — no timestamps, beat labels, or stage directions\n"
            f"- Explain what the viewer is seeing as it builds up\n"
            f"- Accessible to someone new to the topic\n\n"
            f"Respond with ONLY the narration text."
        )
        return call_llm(self.provider, self.model, prompt, max_tokens=600).strip()

    def generate_tts(self, text: str) -> bytes:
        """Generate TTS audio (MP3) using OpenAI tts-1."""
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=text[:4096],
        )
        return response.content

    def create_vtt(self, text: str, video_duration: float) -> str:
        """
        Build WebVTT subtitles from narration text.
        Splits into ~4-second chunks and scales to fit the video duration.
        """
        words = text.split()
        if not words:
            return "WEBVTT\n\n"

        wps = 130 / 60  # words per second
        chunk_size = max(6, int(wps * 4))
        chunks = [words[i : i + chunk_size] for i in range(0, len(words), chunk_size)]

        estimated_total = len(words) / wps
        scale = (video_duration / estimated_total) if estimated_total > 0 else 1.0

        def _t(s: float) -> str:
            h, rem = divmod(s, 3600)
            m, sec = divmod(rem, 60)
            return f"{int(h):02d}:{int(m):02d}:{sec:06.3f}"

        lines = ["WEBVTT", ""]
        cursor = 0.0
        for i, chunk in enumerate(chunks):
            dur = (len(chunk) / wps) * scale
            end = min(cursor + dur, video_duration - 0.05)
            lines += [f"{_t(cursor)} --> {_t(end)}", " ".join(chunk), ""]
            cursor = end

        return "\n".join(lines)

    def merge_audio_video(
        self, video_path: Path, audio_bytes: bytes, output_path: Path
    ) -> Path:
        """Overlay audio on video with ffmpeg. Trims to shortest stream.

        Safe to call with video_path == output_path (writes to a temp file first).
        """
        ffmpeg = _ffmpeg_bin("ffmpeg")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(audio_bytes)
            audio_tmp = Path(tmp.name)

        # Use a unique temp output so in-place (video_path == output_path) is safe
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False, dir=output_path.parent) as out_tmp:
            out_tmp_path = Path(out_tmp.name)

        try:
            r = subprocess.run(
                [ffmpeg, "-y",
                 "-i", str(video_path),
                 "-i", str(audio_tmp),
                 "-c:v", "copy",
                 "-c:a", "aac",
                 "-shortest",
                 "-map", "0:v:0",
                 "-map", "1:a:0",
                 str(out_tmp_path)],
                capture_output=True,
            )
            if r.returncode != 0:
                out_tmp_path.unlink(missing_ok=True)
                raise RuntimeError(
                    f"ffmpeg merge failed: {r.stderr.decode(errors='replace')[:600]}"
                )
            out_tmp_path.replace(output_path)
        finally:
            audio_tmp.unlink(missing_ok=True)

        return output_path

    def get_video_duration(self, video_path: Path) -> float:
        """Return video duration in seconds via ffprobe."""
        return _get_video_duration(video_path)
