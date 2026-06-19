"""Flet app entry point.

Opens a native desktop window (Flet's own Flutter-based runtime — genuine
Material 3 widgets, no CSS approximation) for local runs. Falls back to
plain headless HTTP when `DEMUCS_PYTHON`/`WHISPERX_PYTHON` are set — the same
signal the pipeline already uses to detect it's running inside the Docker
image, where there's no display for a native window to attach to.
"""
from __future__ import annotations

import os

import flet as ft

from .terminal import install_tee
from .views import generate, setup, terminal, video

_DESTINATIONS = [
    ("Generate", ft.Icons.LYRICS_OUTLINED, ft.Icons.LYRICS, generate.build),
    ("Video", ft.Icons.MOVIE_OUTLINED, ft.Icons.MOVIE, video.build),
    ("Terminal", ft.Icons.TERMINAL, ft.Icons.TERMINAL, terminal.build),
    ("Setup", ft.Icons.SETTINGS_OUTLINED, ft.Icons.SETTINGS, setup.build),
]

# Material 3 baseline seed color (the same purple Android's own M3 spec demos use).
_SEED_COLOR = "#6750A4"


def _is_docker() -> bool:
    return bool(os.environ.get("DEMUCS_PYTHON") or os.environ.get("WHISPERX_PYTHON"))


def _build_page(page: ft.Page) -> None:
    page.title = "AiSongTool"
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = ft.Theme(color_scheme_seed=_SEED_COLOR, use_material3=True)
    page.dark_theme = ft.Theme(color_scheme_seed=_SEED_COLOR, use_material3=True)
    page.padding = 0
    if not _is_docker():
        page.window.width = 1320
        page.window.height = 880

    body = ft.Container(expand=True, padding=16)
    active_token = {"value": 0}

    def _show(index: int) -> None:
        active_token["value"] += 1
        _, _, _, builder = _DESTINATIONS[index]
        body.content = builder(page, active_token)
        page.update()

    nav_bar = ft.NavigationBar(
        selected_index=0,
        destinations=[
            ft.NavigationBarDestination(icon=icon, selected_icon=sel_icon, label=label)
            for label, icon, sel_icon, _ in _DESTINATIONS
        ],
        on_change=lambda e: _show(e.control.selected_index),
    )

    page.add(ft.Column([body], expand=True))
    page.navigation_bar = nav_bar
    _show(0)


def main(host: str = "0.0.0.0", port: int = 8000) -> None:
    install_tee()
    if _is_docker():
        ft.run(_build_page, view=ft.AppView.WEB_BROWSER, host=host, port=port)
    else:
        ft.run(_build_page, view=ft.AppView.FLET_APP)
