"""Make Video tab — pick a completed lyrics job, supply a background image,
render an MP4 with word-by-word karaoke-highlighted lyrics burned in."""
from __future__ import annotations

import uuid
from pathlib import Path

from nicegui import events, ui

from .. import jobs
from ..state import JOBS_DIR, is_job_running
from ...video import build_render_cmd

_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _find_job_audio(job_dir: Path) -> Path | None:
    inp = job_dir / "input"
    if not inp.exists():
        return None
    for p in inp.iterdir():
        if p.is_file() and p.suffix.lower() in _AUDIO_EXTENSIONS:
            return p
    return None


def _list_candidate_jobs() -> list[Path]:
    if not JOBS_DIR.exists():
        return []
    out = []
    for d in sorted(JOBS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if d.name == "_uploads" or not d.is_dir():
            continue
        if (d / "out" / "karaoke.ass").exists() and _find_job_audio(d):
            out.append(d)
    return out


def render() -> None:
    job = {"image_path": None, "out_path": None, "returncode": None}

    with ui.row().classes("w-full gap-6 no-wrap items-start"):
        with ui.column().classes("w-96 gap-2"):
            ui.label("1. Pick a completed job").classes("text-bold")
            ui.label("Only jobs generated with lyrics and without segment mode "
                      "have the word-timing data this needs.").classes("text-caption text-grey")
            job_select = ui.select({}, label="Job").classes("w-full")
            ui.button("Refresh list", icon="refresh", on_click=lambda: _refresh_jobs()).props("flat")

            ui.label("2. Background image").classes("text-bold q-mt-md")
            image_upload = ui.upload(label="Background image", auto_upload=True).classes("w-full") \
                .props('accept=".jpg,.jpeg,.png,.webp,.bmp"')

            render_button = ui.button("Render video", icon="movie").classes("w-full q-mt-md")
            status_label = ui.label("Pick a job and upload a background image.").classes("text-grey q-mt-sm")

        with ui.column().classes("flex-1 gap-2") as results_col:
            ui.label("Output").classes("text-bold")
            ui.label("Your rendered video appears here.").classes("text-grey")

    def _refresh_jobs() -> None:
        candidates = _list_candidate_jobs()
        job_select.set_options({str(d): d.name for d in candidates})
        if candidates:
            job_select.value = str(candidates[0])

    _refresh_jobs()

    async def _on_image_upload(e: events.UploadEventArguments) -> None:
        f = e.file
        ext = Path(f.name).suffix.lower()
        if ext not in _IMAGE_EXTENSIONS:
            ui.notify(f"Unsupported image type '{ext}'.", type="negative")
            return
        dest = JOBS_DIR / "_uploads" / f"{uuid.uuid4().hex[:12]}{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        await f.save(dest)
        job["image_path"] = dest
        status_label.set_text(f"Background set: {f.name}")

    image_upload.on_upload(_on_image_upload)

    def _render() -> None:
        if not job_select.value:
            ui.notify("Pick a job first.", type="warning")
            return
        if job["image_path"] is None:
            ui.notify("Upload a background image first.", type="warning")
            return
        if is_job_running():
            ui.notify("A job is already running.", type="warning")
            return

        job_dir = Path(job_select.value)
        audio_path = _find_job_audio(job_dir)
        ass_path = job_dir / "out" / "karaoke.ass"
        if audio_path is None or not ass_path.exists():
            ui.notify("This job is missing karaoke data.", type="negative")
            return

        out_path = job_dir / "out" / "lyric_video.mp4"
        cmd = build_render_cmd(job["image_path"], audio_path, ass_path, out_path)
        job["out_path"] = out_path
        job["returncode"] = None

        def _on_exit(code: int) -> None:
            job["returncode"] = code

        jobs.spawn_cli(cmd, cwd=job_dir, on_exit=_on_exit)
        status_label.set_text("Rendering... see the Terminal tab for live ffmpeg output.")

    render_button.on_click(_render)

    def _poll() -> None:
        if job["out_path"] is None:
            return
        if is_job_running():
            render_button.props("loading")
            return
        render_button.props(remove="loading")
        if job["returncode"] is None:
            return

        out_path: Path = job["out_path"]
        results_col.clear()
        with results_col:
            ui.label("Output").classes("text-bold")
            if job["returncode"] != 0 or not out_path.exists():
                ui.label("Render failed — check the Terminal tab for details.").classes("text-negative")
            else:
                status_label.set_text("Done.")
                ui.video(str(out_path)).classes("w-full")
                ui.button("Download video", icon="download",
                          on_click=lambda: ui.download(out_path, filename=out_path.name))
        job["returncode"] = None

    ui.timer(1.0, _poll)
