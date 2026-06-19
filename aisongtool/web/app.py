"""NiceGUI app entry point.

Opens a native desktop window (pywebview) for local runs. Falls back to plain
headless HTTP when `DEMUCS_PYTHON`/`WHISPERX_PYTHON` are set — the same signal
the pipeline already uses to detect it's running inside the Docker image,
where there's no display for pywebview to attach to.
"""
from __future__ import annotations

import os

from nicegui import ui

from . import layout
from .terminal import install_tee


def _is_docker() -> bool:
    return bool(os.environ.get("DEMUCS_PYTHON") or os.environ.get("WHISPERX_PYTHON"))


@ui.page("/")
def index() -> None:
    layout.build()


def main(host: str = "0.0.0.0", port: int = 8000) -> None:
    install_tee()
    native = not _is_docker()
    ui.run(
        title="AiSongTool",
        native=native,
        host=None if native else host,
        port=0 if native else port,
        show=False,
        window_size=(1320, 880) if native else None,
        reload=False,
        show_welcome_message=False,
    )
