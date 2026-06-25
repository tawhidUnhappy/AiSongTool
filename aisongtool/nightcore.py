"""Nightcore audio/video conversion — speed + pitch up an existing song via
the classic resampling trick, then render a video over a background image.
Same ffmpeg-command-builder style as video.py, used by both the "Nightcore"
and "Song Generation" views (the latter chains ACE-Step generation into this).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .toolrunner import find_ffmpeg

DEFAULT_SPEED = 1.25

# The genre's actual sound is more than the resample trick — community
# nightcore edits near-universally also push a "smile curve" EQ (boosted
# bass + treble, since raising pitch via resample alone can sound thin/
# brittle) and normalize loudness for that punchier, more energetic feel.
NIGHTCORE_ENHANCE_FILTERS = "bass=g=6,treble=g=3,loudnorm=I=-14:TP=-1.5:LRA=11"


def _find_ffprobe() -> str:
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        return ffprobe
    # Fall back to deriving it from ffmpeg's path (same install, same dir).
    return find_ffmpeg().replace("ffmpeg", "ffprobe")


def probe_sample_rate(audio_path: Path) -> int:
    ffprobe = _find_ffprobe()
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate", "-of", "json", str(audio_path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(proc.stdout)
    streams = data.get("streams") or []
    if not streams or not streams[0].get("sample_rate"):
        raise RuntimeError(f"Could not determine sample rate of {audio_path}")
    return int(streams[0]["sample_rate"])


def build_nightcore_audio_cmd(in_path: Path, out_path: Path, speed: float = DEFAULT_SPEED) -> list[str]:
    """The classic nightcore edit: resample as if the track played faster
    (raises pitch and speed together, not an independent tempo stretch),
    plus the EQ/loudness treatment real nightcore edits use (see
    NIGHTCORE_ENHANCE_FILTERS)."""
    ffmpeg = find_ffmpeg()
    rate = probe_sample_rate(in_path)
    new_rate = int(round(rate * speed))
    af = f"asetrate={new_rate},aresample={rate},{NIGHTCORE_ENHANCE_FILTERS}"
    return [
        ffmpeg, "-y",
        "-i", str(in_path),
        "-af", af,
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(out_path),
    ]


def build_nightcore_video_cmd(
    image_path: Path,
    audio_path: Path,
    out_path: Path,
    resolution: tuple[int, int] = (1920, 1080),
) -> list[str]:
    ffmpeg = find_ffmpeg()
    width, height = resolution
    vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    return [
        ffmpeg, "-y",
        "-loop", "1", "-i", str(image_path),
        "-i", str(audio_path),
        "-vf", vf,
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out_path),
    ]
