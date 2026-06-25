"""Shared root-path resolution.

The Electron app is the sole packaging vehicle now (no PyInstaller — this
package always runs from its own `uv`-managed venv, invoked as a subprocess
by `desktop/src/main/paths.ts`). Electron decides where the one self-
contained data root lives (dev repo root / portable-exe folder / per-user
app-data dir — see `paths.ts`'s `dataDir()`) and passes it down via the
`AISONGTOOL_DATA_DIR` env var on every spawned process, so this module never
has to re-derive that logic. Running this package directly (`aisongtool run`/
`aisongtool setup` from a terminal, with no Electron parent) falls back to
the repo root, matching the layout developers already expect.
"""
from __future__ import annotations

import os
from pathlib import Path


def app_root() -> Path:
    """Where the app's own files (workers/, font/) live — the repo root."""
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Writable location for provisioned envs + job data — `AISONGTOOL_DATA_DIR`
    if set (always the case when launched from Electron), else the repo root."""
    override = os.environ.get("AISONGTOOL_DATA_DIR")
    if override:
        d = Path(override)
        d.mkdir(parents=True, exist_ok=True)
        return d
    return app_root()


def workers_dir() -> Path:
    return app_root() / "workers"


def fonts_dir() -> Path:
    """Bundled fonts (e.g. font/Edo/edo.ttf) for the lyric video's subtitle
    track — passed to ffmpeg's `ass` filter as `fontsdir` so libass can find
    them without a system-wide font install."""
    return app_root() / "font"
