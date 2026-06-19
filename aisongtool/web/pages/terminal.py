"""Terminal tab — a live xterm.js view fed by the shared ring buffer in
`web/terminal.py`, so every subprocess this app runs (pipeline, ffmpeg,
`aisongtool setup`) is visible in one place."""
from __future__ import annotations

from nicegui import ui

from .. import terminal as terminal_buffer


def render() -> None:
    with ui.card().classes("w-full h-full q-pa-sm"):
        term = ui.xterm({
            "convertEol": True,
            "scrollback": 20_000,
            "theme": {"background": "#1C1B1F", "foreground": "#E6E1E5"},
        }).classes("w-full h-full")

    cursor = {"pos": 0}

    def _drain() -> None:
        text, new_pos = terminal_buffer.drain(cursor["pos"])
        if text:
            term.write(text)
        cursor["pos"] = new_pos

    ui.timer(0.2, _drain)
