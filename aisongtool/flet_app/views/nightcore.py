"""Nightcore view — pick any song (uploaded, or from any past job) and an
optional background image, produce a sped-up/pitched-up "nightcore" audio +
video. Independent of ACE-Step; see views/songgen.py for the automated
generate-then-nightcore-ify flow that shares the conversion tail with this."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import flet as ft

from . import _nightcore_chain
from .. import jobs
from ..notify import notify
from ..polling import start_poll
from ..state import JOBS_DIR, is_job_running
from ...assets_lib import AUDIO_EXTENSIONS as _AUDIO_EXTENSIONS
from ...assets_lib import IMAGE_EXTENSIONS as _IMAGE_EXTENSIONS
from ...assets_lib import list_audio_assets

_DEFAULT_BG = Path(__file__).resolve().parent.parent / "assets" / "nightcore_default_bg.png"


def build(page: ft.Page, active_token: dict) -> ft.Control:
    job: dict = {"audio_path": None, "image_path": _DEFAULT_BG, "stage": None}

    job_dropdown = ft.Dropdown(label="Pick from uploaded/generated songs (optional)", options=[])
    status_label = ft.Text("Pick or upload a song, then convert.", size=12, color=ft.Colors.OUTLINE)
    audio_label = ft.Text("No song selected.", size=12, color=ft.Colors.OUTLINE)
    image_label = ft.Text("Using default background.", size=12, color=ft.Colors.OUTLINE)
    convert_button = ft.FilledButton("Make nightcore video", icon=ft.Icons.SPEED, disabled=True)

    results_col = ft.Column([
        ft.Text("Output", weight=ft.FontWeight.BOLD),
        ft.Text("Your nightcore audio + video appear here.", size=12, color=ft.Colors.OUTLINE),
    ], spacing=8)

    audio_picker = ft.FilePicker()
    image_picker = ft.FilePicker()
    save_picker = ft.FilePicker()
    page.services.append(audio_picker)
    page.services.append(image_picker)
    page.services.append(save_picker)

    def _refresh_jobs(e: ft.ControlEvent | None = None) -> None:
        candidates = list_audio_assets(JOBS_DIR)
        job_dropdown.options = [ft.DropdownOption(str(a.path), text=a.label) for a in candidates]
        page.update()

    def _on_job_pick(e: ft.ControlEvent) -> None:
        if not job_dropdown.value:
            return
        job["audio_path"] = Path(job_dropdown.value)
        audio_label.value = f"Using: {Path(job_dropdown.value).name}"
        convert_button.disabled = False
        page.update()

    job_dropdown.on_change = _on_job_pick

    async def _pick_audio(e: ft.ControlEvent) -> None:
        files = await audio_picker.pick_files(
            dialog_title="Pick a song",
            allowed_extensions=[ext.lstrip(".") for ext in _AUDIO_EXTENSIONS],
            file_type=ft.FilePickerFileType.CUSTOM, with_data=True,
        )
        if not files:
            return
        f = files[0]
        ext = Path(f.name).suffix.lower()
        if ext not in _AUDIO_EXTENSIONS:
            notify(page, f"Unsupported file type '{ext}'.", error=True)
            return
        dest = JOBS_DIR / "_uploads" / f"{uuid.uuid4().hex[:12]}{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if f.path:
            shutil.copy(f.path, dest)
        elif f.bytes:
            dest.write_bytes(f.bytes)
        else:
            notify(page, "Could not read the picked file.", error=True)
            return
        job["audio_path"] = dest
        audio_label.value = f"Using: {f.name}"
        convert_button.disabled = False
        page.update()

    async def _pick_image(e: ft.ControlEvent) -> None:
        files = await image_picker.pick_files(
            dialog_title="Pick a background image",
            allowed_extensions=[ext.lstrip(".") for ext in _IMAGE_EXTENSIONS],
            file_type=ft.FilePickerFileType.CUSTOM, with_data=True,
        )
        if not files:
            return
        f = files[0]
        ext = Path(f.name).suffix.lower()
        if ext not in _IMAGE_EXTENSIONS:
            notify(page, f"Unsupported image type '{ext}'.", error=True)
            return
        dest = JOBS_DIR / "_uploads" / f"{uuid.uuid4().hex[:12]}{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if f.path:
            shutil.copy(f.path, dest)
        elif f.bytes:
            dest.write_bytes(f.bytes)
        else:
            notify(page, "Could not read the picked image.", error=True)
            return
        job["image_path"] = dest
        image_label.value = f"Background set: {f.name}"
        page.update()

    def _convert(e: ft.ControlEvent) -> None:
        if job["audio_path"] is None:
            notify(page, "Pick a song first.", warning=True)
            return
        if is_job_running():
            notify(page, "A job is already running.", warning=True)
            return
        out_dir = JOBS_DIR / "_nightcore" / uuid.uuid4().hex[:12]
        _nightcore_chain.start(job, job["audio_path"], job["image_path"], out_dir)
        status_label.value = "Starting..."
        page.update()

    convert_button.on_click = _convert

    def _poll() -> None:
        convert_button.disabled = is_job_running() or job["audio_path"] is None
        _nightcore_chain.render_results(page, job, results_col, status_label, save_picker)
        page.update()

    start_poll(page, active_token, 1.0, _poll)
    _refresh_jobs()

    left_card = ft.Card(content=ft.Container(
        ft.Column([
            ft.Text("1. Pick a song", weight=ft.FontWeight.BOLD),
            job_dropdown,
            ft.OutlinedButton("Refresh list", icon=ft.Icons.REFRESH, on_click=_refresh_jobs),
            ft.FilledButton("Or choose a song file", icon=ft.Icons.UPLOAD_FILE, on_click=_pick_audio),
            audio_label,
            ft.Text("2. Background image (optional)", weight=ft.FontWeight.BOLD),
            ft.OutlinedButton("Choose image", icon=ft.Icons.IMAGE, on_click=_pick_image),
            image_label,
            convert_button,
            status_label,
        ], spacing=12, scroll=ft.ScrollMode.AUTO),
        padding=16, width=420,
    ))

    right_card = ft.Card(content=ft.Container(results_col, padding=16, expand=True))

    return ft.Row([left_card, right_card], spacing=16, expand=True, vertical_alignment=ft.CrossAxisAlignment.START)
