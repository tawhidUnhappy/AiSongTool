"""Shared "poll while this view is on screen" helper.

`app.py` gives each destination its own `{"active": bool}` dict, flipped True
when it's the visible one and False otherwise. Views are built once and kept
around (not torn down on navigation, so in-progress state like Create's
`flow` dict survives switching tabs and back) — so this loop runs for the
life of the app, just skipping its tick while the view isn't on screen,
rather than being started fresh on every visit and torn down on every exit."""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

import flet as ft

ActiveToken = dict


def start_poll(page: ft.Page, active_token: ActiveToken, interval: float, tick: Callable[[], Awaitable[None] | None]) -> None:
    async def _loop() -> None:
        while True:
            if active_token.get("active", True):
                try:
                    result = tick()
                    if asyncio.iscoroutine(result):
                        await result
                except RuntimeError as exc:
                    # The window/session can be torn down (app closing) while
                    # this loop is mid-flight — stop quietly instead of
                    # spamming a traceback on every exit.
                    if "destroyed session" in str(exc):
                        return
                    raise
            await asyncio.sleep(interval)

    page.run_task(_loop)
