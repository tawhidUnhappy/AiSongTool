"""Shared "poll while this view is on screen" helper.

`app.py` bumps a shared token every time the bottom NavigationBar switches
views; each view starts a poll loop that stops as soon as the token no
longer matches the value it captured at start, so switching away from a view
cleanly stops its background polling instead of accumulating loops."""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

import flet as ft

ActiveToken = dict


def start_poll(page: ft.Page, active_token: ActiveToken, interval: float, tick: Callable[[], Awaitable[None] | None]) -> None:
    my_token = active_token["value"]

    async def _loop() -> None:
        while active_token["value"] == my_token:
            result = tick()
            if asyncio.iscoroutine(result):
                await result
            await asyncio.sleep(interval)

    page.run_task(_loop)
