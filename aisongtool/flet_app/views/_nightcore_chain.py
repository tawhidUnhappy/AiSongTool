"""Shared "audio -> nightcore audio -> nightcore video -> preview/save" tail,
used by both the Nightcore view (manual) and the Song Generation view (after
ACE-Step produces a song). Not a nav destination on its own.

Caller owns a `job` dict and a poll loop (the same `start_poll` pattern every
other view uses); call `start()` once to kick off the chain, then call
`render_results()` each tick to reflect progress/results."""
from __future__ import annotations

import shutil
from pathlib import Path

import flet as ft
import flet_video as fv

from .. import jobs
from ..notify import notify
from ...nightcore import build_nightcore_audio_cmd, build_nightcore_video_cmd


def start(job: dict, audio_path: Path, image_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    audio_out = out_dir / "nightcore_audio.mp3"
    video_out = out_dir / "nightcore_video.mp4"
    job["stage"] = "audio"
    job["returncode"] = None
    job["rendered"] = False
    job["audio_out"] = audio_out
    job["video_out"] = video_out

    def _on_video_exit(code: int) -> None:
        job["stage"] = "done" if code == 0 else "error"
        job["returncode"] = code

    def _on_audio_exit(code: int) -> None:
        if code != 0:
            job["stage"] = "error"
            job["returncode"] = code
            return
        job["stage"] = "video"
        cmd = build_nightcore_video_cmd(image_path, audio_out, video_out)
        jobs.spawn_cli(cmd, cwd=out_dir, on_exit=_on_video_exit)

    cmd = build_nightcore_audio_cmd(audio_path, audio_out)
    jobs.spawn_cli(cmd, cwd=out_dir, on_exit=_on_audio_exit)


def _status_text(stage: str | None) -> str | None:
    return {
        "audio": "Speeding up + pitching up the audio (nightcore)...",
        "video": "Rendering video... see the Terminal tab for live ffmpeg output.",
        "done": "Done.",
        "error": "Failed — check the Terminal tab for details.",
    }.get(stage)


def render_results(
    page: ft.Page,
    job: dict,
    results_col: ft.Column,
    status_label: ft.Text,
    save_picker: ft.FilePicker,
) -> None:
    """Call every poll tick. Rebuilds `results_col` once when the chain
    finishes (success or failure); cheap no-op ticks otherwise."""
    stage = job.get("stage")
    if stage is None:
        return

    text = _status_text(stage)
    if text:
        status_label.value = text

    if stage not in ("done", "error") or job.get("rendered"):
        page.update()
        return
    job["rendered"] = True

    rows: list[ft.Control] = [ft.Text("Output", weight=ft.FontWeight.BOLD)]
    if stage == "error":
        rows.append(ft.Text("Nightcore conversion failed — check the Terminal tab for details.",
                             color=ft.Colors.ERROR))
    else:
        video_out: Path = job["video_out"]
        audio_out: Path = job["audio_out"]

        async def _save_video(e: ft.ControlEvent) -> None:
            dest = await save_picker.save_file(dialog_title="Save video", file_name=video_out.name)
            if dest:
                shutil.copy(video_out, dest)
                notify(page, f"Saved to {dest}")

        async def _save_audio(e: ft.ControlEvent) -> None:
            dest = await save_picker.save_file(dialog_title="Save audio", file_name=audio_out.name)
            if dest:
                shutil.copy(audio_out, dest)
                notify(page, f"Saved to {dest}")

        rows.append(ft.Container(
            fv.Video(playlist=[fv.VideoMedia(resource=str(video_out))], autoplay=False, expand=True),
            height=360,
        ))
        rows.append(ft.Row([
            ft.FilledTonalButton("Save video", icon=ft.Icons.SAVE_ALT, on_click=_save_video),
            ft.OutlinedButton("Save audio only", icon=ft.Icons.AUDIOTRACK, on_click=_save_audio),
        ], spacing=8))

    results_col.controls = rows
    page.update()
