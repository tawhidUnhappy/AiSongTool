"""Make Video view — pick a completed lyrics job, supply a background image
with a native file dialog, render an MP4 with word-by-word karaoke-
highlighted lyrics burned in, preview it, save a copy."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import flet as ft
import flet_video as fv

from .. import jobs
from ..notify import notify
from ..polling import start_poll
from ..state import JOBS_DIR, is_job_running
from ...assets_lib import IMAGE_EXTENSIONS as _IMAGE_EXTENSIONS
from ...assets_lib import find_audio_in as _find_job_audio
from ...assets_lib import list_karaoke_ready_jobs
from ...video import build_render_cmd


def _list_candidate_jobs() -> list[Path]:
    return list_karaoke_ready_jobs(JOBS_DIR)


def build(page: ft.Page, active_token: dict) -> ft.Control:
    job = {"image_path": None, "out_path": None, "returncode": None}

    job_dropdown = ft.Dropdown(label="Job", options=[])
    status_label = ft.Text("Pick a job and a background image.", size=12, color=ft.Colors.OUTLINE)
    image_label = ft.Text("No background image selected.", size=12, color=ft.Colors.OUTLINE)
    render_button = ft.FilledButton("Render video", icon=ft.Icons.MOVIE, disabled=True)

    results_col = ft.Column([
        ft.Text("Output", weight=ft.FontWeight.BOLD),
        ft.Text("Your rendered video appears here.", size=12, color=ft.Colors.OUTLINE),
    ], spacing=8)

    image_picker = ft.FilePicker()
    save_picker = ft.FilePicker()
    page.services.append(image_picker)
    page.services.append(save_picker)

    def _refresh_jobs(e: ft.ControlEvent | None = None) -> None:
        candidates = _list_candidate_jobs()
        job_dropdown.options = [ft.DropdownOption(str(d), text=d.name) for d in candidates]
        job_dropdown.value = str(candidates[0]) if candidates else None
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
        render_button.disabled = job_dropdown.value is None
        page.update()

    def _render(e: ft.ControlEvent) -> None:
        if not job_dropdown.value:
            notify(page, "Pick a job first.", warning=True)
            return
        if job["image_path"] is None:
            notify(page, "Pick a background image first.", warning=True)
            return
        if is_job_running():
            notify(page, "A job is already running.", warning=True)
            return

        job_dir = Path(job_dropdown.value)
        audio_path = _find_job_audio(job_dir)
        ass_path = job_dir / "out" / "karaoke.ass"
        if audio_path is None or not ass_path.exists():
            notify(page, "This job is missing karaoke data.", error=True)
            return

        out_path = job_dir / "out" / "lyric_video.mp4"
        cmd = build_render_cmd(job["image_path"], audio_path, ass_path, out_path)
        job["out_path"] = out_path
        job["returncode"] = None

        def _on_exit(code: int) -> None:
            job["returncode"] = code

        jobs.spawn_cli(cmd, cwd=job_dir, on_exit=_on_exit)
        status_label.value = "Rendering... see the Terminal tab for live ffmpeg output."
        page.update()

    async def _save_video(e: ft.ControlEvent) -> None:
        out_path: Path = job["out_path"]
        dest = await save_picker.save_file(dialog_title="Save video", file_name=out_path.name)
        if dest:
            shutil.copy(out_path, dest)
            notify(page, f"Saved to {dest}")

    def _poll() -> None:
        running = is_job_running()
        render_button.disabled = running or job_dropdown.value is None or job["image_path"] is None

        if job["out_path"] is None:
            page.update()
            return
        if running:
            page.update()
            return
        if job["returncode"] is None:
            page.update()
            return

        out_path: Path = job["out_path"]
        rows: list[ft.Control] = [ft.Text("Output", weight=ft.FontWeight.BOLD)]
        if job["returncode"] != 0 or not out_path.exists():
            rows.append(ft.Text("Render failed — check the Terminal tab for details.", color=ft.Colors.ERROR))
        else:
            status_label.value = "Done."
            rows.append(ft.Container(
                fv.Video(playlist=[fv.VideoMedia(resource=str(out_path))], autoplay=False, expand=True),
                height=360,
            ))
            rows.append(ft.FilledTonalButton("Save video", icon=ft.Icons.SAVE_ALT, on_click=_save_video))
        results_col.controls = rows
        job["returncode"] = None
        page.update()

    def _on_job_change(e: ft.ControlEvent) -> None:
        render_button.disabled = job_dropdown.value is None or job["image_path"] is None
        page.update()

    job_dropdown.on_change = _on_job_change
    render_button.on_click = _render

    start_poll(page, active_token, 1.0, _poll)
    _refresh_jobs()

    left_card = ft.Card(content=ft.Container(
        ft.Column([
            ft.Text("1. Pick a completed job", weight=ft.FontWeight.BOLD),
            ft.Text("Only jobs generated with lyrics and without segment mode "
                    "have the word-timing data this needs.", size=12, color=ft.Colors.OUTLINE),
            job_dropdown,
            ft.OutlinedButton("Refresh list", icon=ft.Icons.REFRESH, on_click=_refresh_jobs),
            ft.Text("2. Background image", weight=ft.FontWeight.BOLD),
            ft.FilledButton("Choose image", icon=ft.Icons.IMAGE, on_click=_pick_image),
            image_label,
            render_button,
            status_label,
        ], spacing=12, scroll=ft.ScrollMode.AUTO),
        padding=16, width=420,
    ))

    right_card = ft.Card(content=ft.Container(results_col, padding=16, expand=True))

    return ft.Row([left_card, right_card], spacing=16, expand=True, vertical_alignment=ft.CrossAxisAlignment.START)
