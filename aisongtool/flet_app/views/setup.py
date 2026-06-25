"""Setup view — GPU/uv/ffmpeg doctor status, and buttons to (re)provision the
isolated demucs-uv / whisperx-uv environments and the optional tools
(ACE-Step-1.5 music generation, Z-Image-Turbo image generation, Gemma 4
prompt writing)."""
from __future__ import annotations

import sys

import flet as ft

from .. import jobs
from ..notify import notify
from ..polling import start_poll
from ..state import is_job_running
from ...tools_install import doctor
from ._tool_card import tool_install_card


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

    ace_card = tool_install_card(
        page,
        title="Optional: ACE-Step (music generation)",
        description="Prebuilt binaries + GGUF-quantized models (acestep.cpp) downloaded straight "
                    "into acestep-cpp/ — no git clone, no isolated Python/CUDA env of its own "
                    "(~4.2GB total, vs ~11GB for the original diffusers-based ACE-Step-1.5).",
        install_label="Install / update ACE-Step",
        install_cmd=["install-tool", "ace-step"],
        installing_notice="Downloading ACE-Step (acestep.cpp) binaries + models — see the Terminal tab. "
                           "This downloads a few GB and can take a while.",
        extra_button=ft.FilledTonalButton("Open ACE-Step UI", icon=ft.Icons.AUTO_AWESOME, disabled=True),
    )

    def _launch_ace_step(e: ft.ControlEvent) -> None:
        if is_job_running():
            notify(page, "A job is already running.", warning=True)
            return
        jobs.spawn_cli([sys.executable, "-m", "aisongtool.cli", "ace-step"])
        notify(page, "Starting ACE-Step's server — open http://127.0.0.1:8080 in your browser.")

    ace_card.extra_button.on_click = _launch_ace_step

    # Simple "just an isolated env, no extra launch button" tools — built in a
    # loop since they all share the exact same card shape.
    _SIMPLE_TOOLS = [
        ("zimage-uv", "z-image", "Optional: Z-Image-Turbo (image generation)",
         "An isolated `uv` env (like demucs-uv/whisperx-uv) — lets the Create flow generate a "
         "background image straight from the song's prompt instead of needing one uploaded by "
         "hand. Runs comfortably in 8GB VRAM.",
         "Install Z-Image Turbo",
         "Installing Z-Image-Turbo's isolated env — see the Terminal tab. "
         "Model weights (a few GB) download on first real use."),
        ("gemma-uv", "gemma", "Optional: Gemma 4 (prompt writing)",
         "An isolated `uv` env — lets the Create flow turn one short description into a song "
         "style caption, full lyrics, and an image prompt. 4-bit quantized, a few GB VRAM.",
         "Install Gemma 4",
         "Installing Gemma 4's isolated env — see the Terminal tab. "
         "Model weights (a few GB) download on first real use."),
    ]
    simple_cards: dict[str, object] = {}
    for env_name, tool_name, title, description, install_label, installing_notice in _SIMPLE_TOOLS:
        simple_cards[env_name] = tool_install_card(
            page, title=title, description=description, install_label=install_label,
            install_cmd=["install-tool", tool_name], installing_notice=installing_notice,
        )
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
            ace_card.set_status(f"Installed at {ace['dir']}")
            ace_card.extra_button.disabled = False
        elif ace["cloned"]:
            ace_card.set_status("Cloned, but `uv sync` hasn't finished — click Install / update.")
            ace_card.extra_button.disabled = True
        else:
            ace_card.set_status("Not installed yet.")
            ace_card.extra_button.disabled = True

        for env_name, card in simple_cards.items():
            info = report["envs"].get(env_name, {})
            ready = info.get("provisioned") and info.get("venv_python")
            card.set_status("Installed." if ready else "Not installed yet.")

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

    def _poll() -> None:
        running = is_job_running()
        run_button.disabled = running
        ace_card.install_button.disabled = running
        any_pending = pending["finished"] or ace_card.consume_pending()
        for card in simple_cards.values():
            card.install_button.disabled = running
            any_pending = card.consume_pending() or any_pending
        if any_pending:
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
            ace_card.card,
            *[card.card for card in simple_cards.values()],
        ],
        spacing=16,
        expand=True,
    )
