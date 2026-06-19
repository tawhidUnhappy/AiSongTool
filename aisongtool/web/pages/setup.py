"""Setup tab — GPU/uv/ffmpeg doctor status, and a button to (re)provision the
isolated demucs-uv / whisperx-uv environments."""
from __future__ import annotations

import sys

from nicegui import ui

from .. import jobs
from ..state import is_job_running
from ...tools_install import doctor


def _status_row(label: str, ok: bool, detail: str = "") -> None:
    with ui.row().classes("items-center gap-2"):
        ui.icon("check_circle" if ok else "cancel", color="positive" if ok else "negative")
        ui.label(label)
        if detail:
            ui.label(detail).classes("text-grey text-caption")


def render() -> None:
    with ui.row().classes("w-full gap-6 no-wrap items-start"):
        with ui.column().classes("gap-2"):
            run_button = ui.button("Run setup", icon="build")
            refresh_button = ui.button("Refresh status", icon="refresh").props("flat")
        status_col = ui.column().classes("gap-1")

    def _refresh() -> None:
        status_col.clear()
        report = doctor()
        with status_col:
            ui.label("Prerequisites").classes("text-bold")
            _status_row("uv", report["uv"] is not None, report["uv"] or "not found — required")
            _status_row("ffmpeg", report["ffmpeg"] is not None, report["ffmpeg"] or "not found — needed for video export")
            _status_row("NVIDIA GPU", report["nvidia_smi"] is not None, report["nvidia_smi"] or "none detected — CPU mode")

            gpu = report["gpu"]
            if gpu["cuda_available_in_main_env"]:
                ui.label(f"CUDA available in this process: {gpu['cuda_device']}").classes("text-caption text-grey")

            ui.label("Isolated environments").classes("text-bold q-mt-md")
            for name, info in report["envs"].items():
                ok = info["provisioned"] and info["venv_python"] is not None
                _status_row(name, ok, "ready" if ok else "not provisioned — click Run setup below")

    refresh_button.on_click(_refresh)
    _refresh()
    pending = {"finished": False}

    def _run_setup() -> None:
        if is_job_running():
            ui.notify("A job is already running.", type="warning")
            return
        cmd = [sys.executable, "-m", "aisongtool.cli", "setup"]
        pending["finished"] = False
        jobs.spawn_cli(cmd, on_exit=lambda code: pending.__setitem__("finished", True))
        ui.notify("Provisioning started — see the Terminal tab for progress.")

    run_button.on_click(_run_setup)

    def _poll() -> None:
        if is_job_running():
            run_button.props("loading")
        else:
            run_button.props(remove="loading")
        if pending["finished"]:
            pending["finished"] = False
            _refresh()

    ui.timer(1.0, _poll)
