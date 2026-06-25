"""Scans job directories for everything the Flet app's "Create" flow (and the
Tools tab) can offer the user to pick from, instead of re-uploading blind:
every audio/image file ever uploaded or generated, and every past job that
has karaoke-ready lyric timing.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@dataclass(frozen=True)
class Asset:
    path: Path
    label: str
    source: str


def _scan(jobs_dir: Path, extensions: set[str]) -> list[Asset]:
    if not jobs_dir.exists():
        return []
    seen: dict[Path, Asset] = {}
    patterns = ["*/input/*", "_uploads/*", "_songgen/*/*"]
    for pattern in patterns:
        for p in jobs_dir.glob(pattern):
            if not p.is_file() or p.suffix.lower() not in extensions:
                continue
            resolved = p.resolve()
            if resolved in seen:
                continue
            source = p.parent.parent.name if p.parent.name == "input" else p.parent.name
            seen[resolved] = Asset(path=p, label=f"{p.name} ({source})", source=source)
    return sorted(seen.values(), key=lambda a: a.path.stat().st_mtime, reverse=True)


def list_audio_assets(jobs_dir: Path) -> list[Asset]:
    return _scan(jobs_dir, AUDIO_EXTENSIONS)


def list_image_assets(jobs_dir: Path) -> list[Asset]:
    return _scan(jobs_dir, IMAGE_EXTENSIONS)


def list_karaoke_ready_jobs(jobs_dir: Path) -> list[Path]:
    """Job dirs with a karaoke.ass and a matching audio file in input/ — i.e.
    eligible for the lyrics nightcore video render step."""
    if not jobs_dir.exists():
        return []
    out = []
    for d in sorted(jobs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        if not (d / "out" / "karaoke.ass").exists():
            continue
        inp = d / "input"
        if inp.exists() and any(p.suffix.lower() in AUDIO_EXTENSIONS for p in inp.iterdir() if p.is_file()):
            out.append(d)
    return out


def find_audio_in(job_dir: Path) -> Path | None:
    inp = job_dir / "input"
    if not inp.exists():
        return None
    for p in inp.iterdir():
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS:
            return p
    return None
