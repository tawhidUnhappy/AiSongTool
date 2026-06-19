"""Shared in-memory state for the Flet app — one running job at a time,
mirroring the single-job guard the old FastAPI server enforced."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import Popen

from ..paths import data_dir

JOBS_DIR = data_dir() / "jobs"
JOBS_DIR.mkdir(exist_ok=True)


@dataclass
class AppState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    current_process: Popen | None = None
    current_job_dir: Path | None = None


state = AppState()


def is_job_running() -> bool:
    with state.lock:
        proc = state.current_process
        return proc is not None and proc.poll() is None


def set_current_job(proc: Popen | None, job_dir: Path | None) -> None:
    with state.lock:
        state.current_process = proc
        state.current_job_dir = job_dir


def stop_current_job() -> bool:
    with state.lock:
        proc = state.current_process
        if proc is None:
            return False
        try:
            proc.terminate()
        except Exception:
            pass
        state.current_process = None
        state.current_job_dir = None
        return True
