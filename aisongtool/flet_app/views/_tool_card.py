"""Shared "optional tool" card for the Setup view — title/description/install
button/status label, used for both ACE-Step and Z-Image so neither duplicates
the same button-click/notify boilerplate (see setup.py)."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field

import flet as ft

from .. import jobs
from ..notify import notify
from ..state import is_job_running


@dataclass
class ToolCard:
    card: ft.Card
    install_button: ft.FilledButton
    status_label: ft.Text
    extra_button: ft.Control | None
    _pending: dict = field(default_factory=lambda: {"finished": False})

    def set_status(self, text: str) -> None:
        self.status_label.value = text

    def consume_pending(self) -> bool:
        """True (once) if the install command finished since the last call —
        the caller's poll loop uses this to know when to re-run `doctor()`."""
        if self._pending["finished"]:
            self._pending["finished"] = False
            return True
        return False


def tool_install_card(
    page: ft.Page,
    title: str,
    description: str,
    install_label: str,
    install_cmd: list[str],
    installing_notice: str,
    extra_button: ft.Control | None = None,
) -> ToolCard:
    install_button = ft.FilledButton(install_label, icon=ft.Icons.DOWNLOAD)
    status_label = ft.Text("", size=12, color=ft.Colors.OUTLINE)
    card = ToolCard(card=None, install_button=install_button, status_label=status_label,
                     extra_button=extra_button)

    def _install(e: ft.ControlEvent) -> None:
        if is_job_running():
            notify(page, "A job is already running.", warning=True)
            return
        cmd = [sys.executable, "-m", "aisongtool.cli", *install_cmd]
        card._pending["finished"] = False
        jobs.spawn_cli(cmd, on_exit=lambda code: card._pending.__setitem__("finished", True))
        notify(page, installing_notice)

    install_button.on_click = _install

    buttons = [install_button] + ([extra_button] if extra_button is not None else [])
    card.card = ft.Card(content=ft.Container(
        ft.Column([
            ft.Text(title, weight=ft.FontWeight.BOLD),
            ft.Text(description, size=12, color=ft.Colors.OUTLINE),
            ft.Row(buttons, spacing=8),
            status_label,
        ], spacing=12),
        padding=16,
    ))
    return card
