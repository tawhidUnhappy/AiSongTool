"""Setup view — GPU/uv/ffmpeg doctor status, and buttons to (re)provision the
isolated demucs-uv / whisperx-uv environments and the optional ACE-Step-1.5
music generation tool."""
from __future__ import annotations

import sys

import flet as ft

from .. import jobs
from ..notify import notify
from ..polling import start_poll
from ..state import is_job_running
from ...tools_install import doctor


def _status_row(label: str, ok: bool, detail: str = "") -> ft.Row:
    children = [
        ft.Icon(ft.Icons.CHECK_CIRCLE if ok else ft.Icons.CANCEL,
                color=ft.Colors.PRIMARY if ok else ft.Colors.ERROR, size=18),
        ft.Text(label),
    ]
    if detail:
        children.append(ft.Text(detail, size=12, color=ft.Colors.OUTLINE))
    return ft.Row(children, spacing=8)


def build(page: ft.Page, active_token: dict) -> ft.Control:
    status_col = ft.Column(spacing=4)
    run_button = ft.FilledButton("Run setup", icon=ft.Icons.BUILD)
    refresh_button = ft.OutlinedButton("Refresh status", icon=ft.Icons.REFRESH)

    install_ace_button = ft.FilledButton("Install / update ACE-Step", icon=ft.Icons.DOWNLOAD)
    launch_ace_button = ft.FilledTonalButton("Open ACE-Step UI (Gradio)", icon=ft.Icons.AUTO_AWESOME, disabled=True)
    ace_status_label = ft.Text("", size=12, color=ft.Colors.OUTLINE)

    pending = {"finished": False}

    def _refresh(e: ft.ControlEvent | None = None) -> None:
        report = doctor()
        rows: list[ft.Control] = [ft.Text("Prerequisites", weight=ft.FontWeight.BOLD)]
        rows.append(_status_row("uv", report["uv"] is not None, report["uv"] or "not found — required"))
        rows.append(_status_row("ffmpeg", report["ffmpeg"] is not None,
                                 report["ffmpeg"] or "not found — needed for video export"))
        rows.append(_status_row("NVIDIA GPU", report["nvidia_smi"] is not None,
                                 report["nvidia_smi"] or "none detected — CPU mode"))

        gpu = report["gpu"]
        if gpu["cuda_available_in_main_env"]:
            rows.append(ft.Text(f"CUDA available in this process: {gpu['cuda_device']}",
                                 size=12, color=ft.Colors.OUTLINE))

        rows.append(ft.Text("Isolated environments", weight=ft.FontWeight.BOLD))
        for name, info in report["envs"].items():
            ok = info["provisioned"] and info["venv_python"] is not None
            rows.append(_status_row(name, ok, "ready" if ok else "not provisioned — click Run setup below"))

        status_col.controls = rows

        ace = report["ace_step"]
        if ace["synced"]:
            ace_status_label.value = f"Installed at {ace['dir']}"
            launch_ace_button.disabled = False
        elif ace["cloned"]:
            ace_status_label.value = "Cloned, but `uv sync` hasn't finished — click Install / update."
            launch_ace_button.disabled = True
        else:
            ace_status_label.value = "Not installed yet."
            launch_ace_button.disabled = True

        page.update()

    refresh_button.on_click = _refresh

    def _run_setup(e: ft.ControlEvent) -> None:
        if is_job_running():
            notify(page, "A job is already running.", warning=True)
            return
        cmd = [sys.executable, "-m", "aisongtool.cli", "setup"]
        pending["finished"] = False
        jobs.spawn_cli(cmd, on_exit=lambda code: pending.__setitem__("finished", True))
        notify(page, "Provisioning started — see the Terminal tab for progress.")

    run_button.on_click = _run_setup

    def _install_ace_step(e: ft.ControlEvent) -> None:
        if is_job_running():
            notify(page, "A job is already running.", warning=True)
            return
        cmd = [sys.executable, "-m", "aisongtool.cli", "install-tool", "ace-step"]
        pending["finished"] = False
        jobs.spawn_cli(cmd, on_exit=lambda code: pending.__setitem__("finished", True))
        notify(page, "Cloning + installing ACE-Step-1.5 — see the Terminal tab. "
                     "This downloads several GB and can take a while.")

    install_ace_button.on_click = _install_ace_step

    def _launch_ace_step(e: ft.ControlEvent) -> None:
        if is_job_running():
            notify(page, "A job is already running.", warning=True)
            return
        cmd = [sys.executable, "-m", "aisongtool.cli", "ace-step", "app"]
        jobs.spawn_cli(cmd)
        notify(page, "Starting ACE-Step's Gradio UI — see the Terminal tab for the URL "
                     "(usually http://127.0.0.1:7860).")

    launch_ace_button.on_click = _launch_ace_step

    def _poll() -> None:
        running = is_job_running()
        run_button.disabled = running
        install_ace_button.disabled = running
        if pending["finished"]:
            pending["finished"] = False
            _refresh()
        else:
            page.update()

    start_poll(page, active_token, 1.0, _poll)
    _refresh()

    return ft.ListView(
        controls=[
            ft.Card(content=ft.Container(
                ft.Column([ft.Row([run_button, refresh_button], spacing=8), status_col], spacing=12),
                padding=16,
            )),
            ft.Card(content=ft.Container(
                ft.Column([
                    ft.Text("Optional: ACE-Step-1.5 (music generation)", weight=ft.FontWeight.BOLD),
                    ft.Text("Cloned + `uv sync`'d into its own isolated env — its large, fast-moving "
                            "dependency set (vLLM, diffusers, its own CUDA torch build) never touches "
                            "the main app or the demucs-uv/whisperx-uv envs.",
                            size=12, color=ft.Colors.OUTLINE),
                    ft.Row([install_ace_button, launch_ace_button], spacing=8),
                    ace_status_label,
                ], spacing=12),
                padding=16,
            )),
        ],
        spacing=16,
        expand=True,
    )
