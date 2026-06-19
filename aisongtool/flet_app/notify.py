"""Tiny snackbar helper shared by every view."""
from __future__ import annotations

import flet as ft


def notify(page: ft.Page, message: str, *, error: bool = False, warning: bool = False) -> None:
    color = ft.Colors.ERROR_CONTAINER if error else (ft.Colors.SECONDARY_CONTAINER if warning else None)
    page.show_dialog(ft.SnackBar(ft.Text(message), bgcolor=color))
