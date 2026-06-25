"""Shared root-path resolution — works both in dev/uv mode and inside a frozen
PyInstaller build, where files are unpacked next to the executable rather than
laid out as a normal Python package.
"""
from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    """Where the app's own files (e.g. workers/) live — next to the frozen
    exe, or the repo root in dev/uv mode."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Writable location for provisioned envs + job data.

    In dev/uv mode this is the repo root, matching the existing demucs-uv/,
    whisperx-uv/, jobs/ layout developers already expect. A frozen install
    typically lands in Program Files (not user-writable), so there it's a
    per-user directory instead — same reasoning as mangaEasy's `~/.mangaeasy`.
    """
    if getattr(sys, "frozen", False):
        d = Path.home() / ".aisongtool"
        d.mkdir(parents=True, exist_ok=True)
        return d
    return app_root()


def bundle_dir() -> Path:
    """Where bundled data files (workers/, icons) live.

    PyInstaller >=6's one-dir builds put `datas` under an `_internal/`
    subfolder next to the exe (`sys._MEIPASS`), not next to the exe itself —
    unlike `app_root()`, which is the exe's own directory.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    return app_root()


def workers_dir() -> Path:
    return bundle_dir() / "workers"


def fonts_dir() -> Path:
    """Bundled fonts (e.g. font/Edo/edo.ttf) for the lyric video's subtitle
    track — passed to ffmpeg's `ass` filter as `fontsdir` so libass can find
    them without a system-wide font install."""
    return bundle_dir() / "font"
