"""Subprocess spawning + output streaming, shared by every page that runs an
external command (the pipeline CLI, ffmpeg, `aisongtool setup`)."""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Callable

from . import terminal
from .state import set_current_job

OnExit = Callable[[int], None]


def spawn_cli(cmd: list[str], cwd: Path | None = None, on_exit: OnExit | None = None) -> subprocess.Popen:
    """Run `cmd`, streaming combined stdout/stderr into the terminal ring
    buffer line-by-line, and report the exit code via `on_exit`.

    `on_exit` runs on a background thread — it must only mutate plain data
    (flags, dicts), never touch `ui.*` elements directly. Pages poll that data
    with their own `ui.timer` instead (see web/pages/generate.py)."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONUTF8"] = "1"

    proc = subprocess.Popen(
        cmd, cwd=str(cwd) if cwd is not None else None, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace", bufsize=1,
    )
    set_current_job(proc, cwd)
    terminal.append(f"$ (cwd={cwd}) {' '.join(cmd)}\n")

    def _pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            terminal.append(line)
        proc.wait()
        set_current_job(None, None)
        if on_exit:
            on_exit(proc.returncode or 0)

    threading.Thread(target=_pump, daemon=True).start()
    return proc
