from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _ffmpeg_bin(name: str = "ffmpeg") -> str:
    found = shutil.which(name)
    if found:
        return found
    fallback = Path.home() / "miniforge3" / "bin" / name
    return str(fallback) if fallback.exists() else name


def get_video_duration(video_path: Path) -> float:
    """Return video duration in seconds via ffprobe. Falls back to 30.0 on error."""
    r = subprocess.run(
        [_ffmpeg_bin("ffprobe"), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 30.0
