"""Shared tab chrome wrapping the four pages."""
from __future__ import annotations

from nicegui import ui

from .pages import generate, setup, terminal, video


def build() -> None:
    ui.page_title("AiSongTool")

    with ui.header().classes("items-center"):
        ui.label("AiSongTool").classes("text-xl font-bold q-mr-lg")
        with ui.tabs().classes("text-white") as tabs:
            ui.tab("generate", label="Generate Subtitles", icon="lyrics")
            ui.tab("video", label="Make Video", icon="movie")
            ui.tab("terminal", label="Terminal", icon="terminal")
            ui.tab("setup", label="Setup", icon="settings")

    with ui.tab_panels(tabs, value="generate").classes("w-full"):
        with ui.tab_panel("generate"):
            generate.render()
        with ui.tab_panel("video"):
            video.render()
        with ui.tab_panel("terminal"):
            terminal.render()
        with ui.tab_panel("setup"):
            setup.render()
