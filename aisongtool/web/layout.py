"""Shared tab chrome wrapping the four pages."""
from __future__ import annotations

from nicegui import ui

from . import theme
from .pages import generate, setup, terminal, video


def build() -> None:
    ui.page_title("AiSongTool")
    theme.apply()

    with ui.header().classes("items-center q-px-md"):
        ui.icon("graphic_eq").classes("text-2xl q-mr-sm")
        ui.label("AiSongTool").classes("text-xl font-medium q-mr-lg")
        with ui.tabs().props("dense").classes("text-white") as tabs:
            ui.tab("generate", label="Generate Subtitles", icon="lyrics")
            ui.tab("video", label="Make Video", icon="movie")
            ui.tab("terminal", label="Terminal", icon="terminal")
            ui.tab("setup", label="Setup", icon="settings")

    with ui.tab_panels(tabs, value="generate").classes("w-full q-pa-md"):
        with ui.tab_panel("generate"):
            generate.render()
        with ui.tab_panel("video"):
            video.render()
        with ui.tab_panel("terminal"):
            terminal.render()
        with ui.tab_panel("setup"):
            setup.render()
