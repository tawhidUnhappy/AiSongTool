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
from .views import create, setup, terminal, tools

_DESTINATIONS = [
    ("Create", ft.Icons.AUTO_AWESOME_OUTLINED, ft.Icons.AUTO_AWESOME, create.build),
    ("Tools", ft.Icons.BUILD_OUTLINED, ft.Icons.BUILD, tools.build),
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
    # Built once per destination, lazily, and kept around — not rebuilt on
    # every nav click. Rebuilding from scratch used to silently orphan
    # anything in progress: a long-running background thread (e.g. the
    # Create flow's pipeline) keeps mutating the `flow` dict it captured at
    # build time, but a fresh builder() call makes a brand new `flow` with
    # nothing watching the old one, so switching tabs and back looked like
    # the whole run had been forgotten.
    built: dict[int, ft.Control] = {}
    # One active-flag dict per destination (not one shared counter) — each
    # view's start_poll() loop just checks its own "am I the visible one
    # right now" flag every tick forever, instead of being torn down and
    # needing to be recreated from scratch on every visit.
    active_tokens = [{"active": False} for _ in _DESTINATIONS]

    def _show(index: int) -> None:
        for token in active_tokens:
            token["active"] = False
        active_tokens[index]["active"] = True
        if index not in built:
            _, _, _, builder = _DESTINATIONS[index]
            built[index] = builder(page, active_tokens[index])
        body.content = built[index]
        page.update()

    nav_bar = ft.NavigationBar(
        selected_index=0,
        label_behavior=ft.NavigationBarLabelBehavior.ONLY_SHOW_SELECTED,
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
