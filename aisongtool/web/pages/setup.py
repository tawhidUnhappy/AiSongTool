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
    with ui.column().classes("w-full gap-4"):
        with ui.card().classes("w-full q-pa-md gap-2"):
            with ui.row().classes("w-full gap-6 no-wrap items-start"):
                with ui.column().classes("gap-2"):
                    run_button = ui.button("Run setup", icon="build")
                    refresh_button = ui.button("Refresh status", icon="refresh").props("flat")
                status_col = ui.column().classes("gap-1")

        with ui.card().classes("w-full q-pa-md gap-2"):
            ui.label("Optional: ACE-Step-1.5 (music generation)").classes("text-bold")
            ui.label("Cloned + `uv sync`'d into its own isolated env — its large, fast-moving "
                     "dependency set (vLLM, diffusers, its own CUDA torch build) never touches "
                     "the main app or the demucs-uv/whisperx-uv envs.").classes("text-caption text-grey")
            with ui.row().classes("gap-2 q-mt-sm"):
                install_ace_button = ui.button("Install / update ACE-Step", icon="download")
                launch_ace_button = ui.button("Open ACE-Step UI (Gradio)", icon="auto_awesome")
            ace_status_label = ui.label("").classes("text-caption text-grey")

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

        ace = report["ace_step"]
        if ace["synced"]:
            ace_status_label.set_text(f"Installed at {ace['dir']}")
            launch_ace_button.enable()
        elif ace["cloned"]:
            ace_status_label.set_text("Cloned, but `uv sync` hasn't finished — click Install / update.")
            launch_ace_button.disable()
        else:
            ace_status_label.set_text("Not installed yet.")
            launch_ace_button.disable()

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

    def _install_ace_step() -> None:
        if is_job_running():
            ui.notify("A job is already running.", type="warning")
            return
        cmd = [sys.executable, "-m", "aisongtool.cli", "install-tool", "ace-step"]
        pending["finished"] = False
        jobs.spawn_cli(cmd, on_exit=lambda code: pending.__setitem__("finished", True))
        ui.notify("Cloning + installing ACE-Step-1.5 — see the Terminal tab. "
                   "This downloads several GB and can take a while.")

    install_ace_button.on_click(_install_ace_step)

    def _launch_ace_step() -> None:
        if is_job_running():
            ui.notify("A job is already running.", type="warning")
            return
        cmd = [sys.executable, "-m", "aisongtool.cli", "ace-step", "app"]
        jobs.spawn_cli(cmd)
        ui.notify("Starting ACE-Step's Gradio UI — see the Terminal tab for the URL "
                   "(usually http://127.0.0.1:7860).")

    launch_ace_button.on_click(_launch_ace_step)

    def _poll() -> None:
        if is_job_running():
            run_button.props("loading")
            install_ace_button.props("loading")
        else:
            run_button.props(remove="loading")
            install_ace_button.props(remove="loading")
        if pending["finished"]:
            pending["finished"] = False
            _refresh()

    ui.timer(1.0, _poll)
