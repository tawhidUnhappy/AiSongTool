"""Terminal view — a live log pane fed by the shared ring buffer in
`flet_app/terminal.py`, so every subprocess this app runs (pipeline, ffmpeg,
`aisongtool setup`) is visible in one place."""
from __future__ import annotations

import flet as ft

from .. import terminal as terminal_buffer
from ..polling import start_poll


def build(page: ft.Page, active_token: dict) -> ft.Control:
    log_text = ft.Text(
        "",
        font_family="Consolas, monospace",
        size=12,
        selectable=True,
        color=ft.Colors.ON_SURFACE,
    )
    list_view = ft.ListView(controls=[log_text], expand=True, auto_scroll=True, spacing=0)
    card = ft.Card(
        content=ft.Container(list_view, padding=12, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH),
        expand=True,
    )

    cursor = {"pos": 0}

    def _drain() -> None:
        text, new_pos = terminal_buffer.drain(cursor["pos"])
        if text:
            log_text.value += text
            list_view.update()
        cursor["pos"] = new_pos

    start_poll(page, active_token, 0.3, _drain)
    return card
