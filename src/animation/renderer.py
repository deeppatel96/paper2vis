"""
Manim rendering wrapper.

Writes a Manim scene to a temp file and invokes `manim render` as a subprocess,
returning the path to the rendered .mp4.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path


class ManimRenderer:
    """Renders Manim Python source to an .mp4 file."""

    def __init__(
        self,
        quality: str = "medium_quality",  # low_quality | medium_quality | high_quality
        preview: bool = False,
    ):
        """
        Args:
            quality: Manim quality flag. Maps to -ql / -qm / -qh.
            preview: If True, open the rendered video after rendering.
        """
        self.quality = quality
        self.preview = preview

    # ------------------------------------------------------------------

    def render(self, code: str, output_dir: str | Path) -> Path:
        """
        Write Manim code to a temp file and render it.

        Args:
            code: Complete Python source containing a Scene subclass.
            output_dir: Directory where the .mp4 should be written.

        Returns:
            Path to the rendered .mp4 file.

        Raises:
            RuntimeError: If Manim exits with a non-zero return code.
            FileNotFoundError: If the output video isn't found after rendering.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Write code to a temporary .py file
        with tempfile.NamedTemporaryFile(
            suffix=".py", prefix="manim_scene_", mode="w", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(code)
            scene_file = Path(tmp.name)

        try:
            scene_class = self._detect_scene_class(code)
            quality_flag = self._quality_flag()

            cmd = [
                "manim",
                "render",
                quality_flag,
                "--output_file", scene_class,
                "--media_dir", str(output_dir),
                str(scene_file),
                scene_class,
            ]
            if not self.preview:
                cmd.append("--disable_caching")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"Manim render failed (exit {result.returncode}).\n"
                    f"STDOUT:\n{result.stdout}\n"
                    f"STDERR:\n{result.stderr}"
                )

            # Find the rendered video
            mp4_path = self._find_output_video(output_dir, scene_class)
            return mp4_path

        finally:
            scene_file.unlink(missing_ok=True)

    # ------------------------------------------------------------------

    def _detect_scene_class(self, code: str) -> str:
        """Extract the first Scene subclass name from the source code."""
        match = re.search(r"class\s+(\w+)\s*\(.*?Scene.*?\)", code)
        if match:
            return match.group(1)
        raise ValueError("No Scene subclass found in generated Manim code.")

    def _quality_flag(self) -> str:
        mapping = {
            "low_quality": "-ql",
            "medium_quality": "-qm",
            "high_quality": "-qh",
        }
        return mapping.get(self.quality, "-qm")

    def _find_output_video(self, output_dir: Path, scene_class: str) -> Path:
        """
        Search for the rendered .mp4 in Manim's output directory structure.
        Manim nests output under media/videos/<filename>/<quality>/<SceneName>.mp4
        """
        # Walk the tree looking for the expected file
        for candidate in output_dir.rglob("*.mp4"):
            if scene_class in candidate.stem:
                return candidate

        # Broader fallback: any mp4 in the output dir
        mp4_files = sorted(output_dir.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if mp4_files:
            return mp4_files[0]

        raise FileNotFoundError(
            f"Could not find rendered .mp4 for scene '{scene_class}' under {output_dir}"
        )
