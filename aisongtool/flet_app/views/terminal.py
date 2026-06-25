"""Terminal view — a live log pane fed by the shared ring buffer in
`flet_app/terminal.py`, so every subprocess this app runs (pipeline, ffmpeg,
`aisongtool setup`) is visible in one place."""
from __future__ import annotations

import flet as ft

from .. import terminal as terminal_buffer
from ..polling import start_poll

_FONT_FAMILY = "Consolas"
# font_family doesn't support comma-separated fallback the way CSS does
# (Flutter only looks up one literal name there) — subprocess output
# regularly includes non-Latin scripts and symbols Consolas doesn't have
# glyphs for (Bengali, CJK, emoji, box-drawing, ...), which show up as
# boxes/mojibake without an explicit fallback list.
_FONT_FALLBACK = [
    "Cascadia Mono", "Segoe UI", "Segoe UI Symbol", "Segoe UI Emoji",
    "Nirmala UI", "Microsoft YaHei", "Malgun Gothic", "Noto Sans",
]
_DEFAULT_TEXT_COLOR = ft.Colors.ON_SURFACE


def _style_for(attrs: tuple | None) -> ft.TextStyle:
    color = _DEFAULT_TEXT_COLOR
    weight = None
    italic = False
    decoration = None
    if attrs is not None:
        fg, bold, italics, underscore, strikethrough = attrs
        resolved = terminal_buffer.resolve_color(fg)
        if resolved is not None:
            color = resolved
        if bold:
            weight = ft.FontWeight.BOLD
        italic = bool(italics)
        if strikethrough:
            decoration = ft.TextDecoration.LINE_THROUGH
        elif underscore:
            decoration = ft.TextDecoration.UNDERLINE
    return ft.TextStyle(
        font_family=_FONT_FAMILY, font_family_fallback=_FONT_FALLBACK, size=12,
        color=color, weight=weight, italic=italic, decoration=decoration,
    )


def _build_spans(lines: list[list[tuple[str, tuple]]]) -> list[ft.TextSpan]:
    spans: list[ft.TextSpan] = []
    for i, line in enumerate(lines):
        if i > 0:
            spans.append(ft.TextSpan("\n", style=_style_for(None)))
        for text, attrs in line:
            spans.append(ft.TextSpan(text, style=_style_for(attrs)))
    return spans


def build(page: ft.Page, active_token: dict) -> ft.Control:
    log_text = ft.Text("", selectable=True, spans=[])
    list_view = ft.ListView(controls=[log_text], expand=True, auto_scroll=True, spacing=0)
    card = ft.Card(
        content=ft.Container(list_view, padding=12, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH),
        expand=True,
    )

    last_version = {"value": -1}

    def _refresh() -> None:
        lines, version = terminal_buffer.render_spans()
        if version == last_version["value"]:
            return
        last_version["value"] = version
        # Full replace, not append: a \r-updated progress line (ffmpeg,
        # tqdm) can shrink or change rather than only grow.
        log_text.spans = _build_spans(lines)
        list_view.update()

    start_poll(page, active_token, 0.3, _refresh)
    return card
