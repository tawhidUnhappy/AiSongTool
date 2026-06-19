"""Render an MP4 from a still background image + audio + a karaoke ASS track.

Used by the "Make Video" tab — operates on a completed pipeline job's
`karaoke.ass` (see pipeline_core.run_pipeline / karaoke.py), so it can run
standalone, well after the transcription/alignment step finished.
"""
from __future__ import annotations

from pathlib import Path

from .logging_utils import log
from .toolrunner import find_ffmpeg, run_cmd


def _escape_for_ass_filter(path: Path) -> str:
    """Escape a path for use inside ffmpeg's `ass=...`/`subtitles=...` filter
    argument, where `:` and `\\` are filter-syntax metacharacters."""
    s = str(path.resolve()).replace("\\", "/")
    return s.replace(":", "\\:")


def build_render_cmd(
    background_image: Path,
    audio_path: Path,
    karaoke_ass_path: Path,
    out_path: Path,
    resolution: tuple[int, int] = (1920, 1080),
) -> list[str]:
    """Build the ffmpeg command line for the lyric video. Split out from
    `render_lyric_video` so the web UI can run it via `web.jobs.spawn_cli`
    (live-streamed into the Terminal tab) instead of blocking synchronously."""
    ffmpeg = find_ffmpeg()
    width, height = resolution
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"ass='{_escape_for_ass_filter(karaoke_ass_path)}'"
    )
    return [
        ffmpeg, "-y",
        "-loop", "1", "-i", str(background_image),
        "-i", str(audio_path),
        "-vf", vf,
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out_path),
    ]


def render_lyric_video(
    background_image: Path,
    audio_path: Path,
    karaoke_ass_path: Path,
    out_path: Path,
    log_path: Path,
    resolution: tuple[int, int] = (1920, 1080),
) -> Path:
    """Synchronous, blocking render — for CLI/script use. The web UI uses
    `build_render_cmd` + `jobs.spawn_cli` instead so it doesn't block the
    NiceGUI event loop."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_render_cmd(background_image, audio_path, karaoke_ass_path, out_path, resolution)
    log("Step: Render lyric video (ffmpeg)", log_path)
    run_cmd(cmd, cwd=out_path.parent, log_path=log_path)

    if not out_path.exists():
        raise RuntimeError("ffmpeg did not produce an output video")
    return out_path
