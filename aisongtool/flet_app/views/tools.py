"""Tools — single-purpose utilities for power users: generate subtitles only,
render a plain (non-nightcore) lyric video, or nightcore-ify any song without
lyrics. The main "Create" view chains all of this automatically; these stay
available individually here."""
from __future__ import annotations

import flet as ft

from . import generate, nightcore, video

_TABS = [
    ("Subtitles", ft.Icons.LYRICS, generate),
    ("Lyric Video", ft.Icons.MOVIE, video),
    ("Nightcore", ft.Icons.SPEED, nightcore),
]


def build(page: ft.Page, active_token: dict) -> ft.Control:
    return ft.Tabs(
        length=len(_TABS),
        expand=True,
        content=ft.Column(
            expand=True,
            controls=[
                ft.TabBar(tabs=[ft.Tab(label=label, icon=icon) for label, icon, _ in _TABS]),
                ft.TabBarView(
                    expand=True,
                    controls=[
                        ft.Container(content=mod.build(page, active_token), padding=16)
                        for _, _, mod in _TABS
                    ],
                ),
            ],
        ),
    )
