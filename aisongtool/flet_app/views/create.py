"""Create — the main guided flow. Set everything up first (song source,
lyrics, background image, output folder), then click one "Run" button: song
generation/selection -> vocal separation + subtitle/karaoke generation ->
lyrics nightcore video render, all the way through, automatically.

Each tool runs to completion and exits before the next one starts (ACE-Step's
API server is explicitly shut down right after it produces a song, Demucs/
WhisperX/ffmpeg subprocesses are waited on fully via `jobs.run_blocking`) so
GPU/CPU is freed between stages rather than stacking up. Single-purpose tools
(subtitle-only, plain lyric video, plain nightcore) live in the Tools tab.
"""
from __future__ import annotations

import shutil
import threading
import time
import uuid
from pathlib import Path

import flet as ft
import flet_video as fv

from ..notify import notify
from ..polling import start_poll
from ..state import JOBS_DIR, is_job_running
from ...assets_lib import (
    AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, find_audio_in, list_audio_assets, list_image_assets,
)
from . import _create_pipeline as pipeline

_DEFAULT_BG = Path(__file__).resolve().parent.parent / "assets" / "nightcore_default_bg.png"

_SUBTITLE_OUTPUTS = [
    ("srt", "final.srt", "Subtitles (.srt)"),
    ("ass", "final.ass", "Styled (.ass)"),
    ("vtt", "final.vtt", "Web (.vtt)"),
    ("lrc", "final.lrc", "Music player (.lrc)"),
    ("sbv", "final.sbv", "YouTube (.sbv)"),
]


def build(page: ft.Page, active_token: dict) -> ft.Control:
    flow: dict = {
        "output_dir": None,
        "song_mode": "generate",
        "existing_song_path": None,
        "image_path": _DEFAULT_BG,
        "busy": False,
        "stage": None,
        "stage_started_at": None,
        "gen_progress_text": None,
        "rendered": False,
        "error_message": None,
        "job_dir": None,
        "song_path": None,
        "pipeline_returncode": None,
        "render_returncode": None,
        "video_out": None,
        "audio_out": None,
    }

    # ---- output folder ----------------------------------------------------------
    output_dir_label = ft.Text("Not set — files will use \"save a copy\" prompts instead.",
                                size=12, color=ft.Colors.OUTLINE)
    output_dir_picker = ft.FilePicker()
    page.services.append(output_dir_picker)

    async def _pick_output_dir(e: ft.ControlEvent) -> None:
        path = await output_dir_picker.get_directory_path(dialog_title="Choose output folder")
        if path:
            flow["output_dir"] = Path(path)
            output_dir_label.value = f"Saving final files to: {path}"
            page.update()

    # ---- song source --------------------------------------------------------------
    gen_mode_radio = ft.RadioGroup(
        value="manual",
        content=ft.Row([
            ft.Radio(value="manual", label="I'll write the lyrics"),
            ft.Radio(value="auto", label="Let AI write the song — just describe it"),
            ft.Radio(value="gemma", label="Let Gemma 4 write everything (style + lyrics + image prompt)"),
        ]),
    )
    prompt_field = ft.TextField(label="Prompt (music description)", multiline=True, min_lines=2, max_lines=3,
                                 hint_text="e.g. upbeat synth-pop, female vocals, energetic")
    gen_lyrics_field = ft.TextField(label="Lyrics", multiline=True, min_lines=4, max_lines=6,
                                     hint_text="Lyrics are needed for the final lyrics video.")
    gen_instrumental_checkbox = ft.Checkbox(label="No vocals (instrumental)", value=False)
    gen_thinking_checkbox = ft.Checkbox(label="Better quality (slower — uses the AI songwriting model)",
                                         value=False)
    gen_language_dropdown = ft.Dropdown(
        label="Vocal language", value="unknown",
        options=[
            ft.DropdownOption("unknown", text="Auto"),
            ft.DropdownOption("en", text="English"), ft.DropdownOption("ja", text="Japanese"),
            ft.DropdownOption("ko", text="Korean"), ft.DropdownOption("zh", text="Chinese"),
            ft.DropdownOption("es", text="Spanish"), ft.DropdownOption("fr", text="French"),
            ft.DropdownOption("de", text="German"), ft.DropdownOption("hi", text="Hindi"),
            ft.DropdownOption("ar", text="Arabic"),
        ],
    )
    gen_seed_field = ft.TextField(label="Seed (optional)", hint_text="Leave blank for a random result each time",
                                   width=200)
    duration_slider = ft.Slider(min=10, max=240, value=60, divisions=23, label="{value}s")
    duration_label = ft.Text("Duration: 60s", size=12, color=ft.Colors.OUTLINE)

    asset_dropdown = ft.Dropdown(label="Pick an existing song", options=[])
    existing_lyrics_field = ft.TextField(label="Lyrics for this song (optional, improves alignment)",
                                          multiline=True, min_lines=2, max_lines=4)
    existing_song_label = ft.Text("No song selected.", size=12, color=ft.Colors.OUTLINE)

    mode_radio = ft.RadioGroup(
        value="generate",
        content=ft.Row([
            ft.Radio(value="generate", label="Generate a new song"),
            ft.Radio(value="existing", label="Use an existing song"),
        ]),
    )

    image_source_radio = ft.RadioGroup(
        value="auto",
        content=ft.Row([
            ft.Radio(value="auto", label="Generate from the song's prompt (Z-Image-Turbo)"),
            ft.Radio(value="pick", label="Pick or upload an image"),
        ]),
    )
    image_dropdown = ft.Dropdown(label="Pick an existing image (optional)", options=[], disabled=True)
    upload_image_button = ft.OutlinedButton("Upload new image", icon=ft.Icons.IMAGE, disabled=True)
    image_label = ft.Text("Using default background.", size=12, color=ft.Colors.OUTLINE)

    run_button = ft.FilledButton("Run", icon=ft.Icons.PLAY_ARROW)
    status_label = ft.Text("Set everything up, then click Run.", size=12, color=ft.Colors.OUTLINE)

    generated_col = ft.Column([
        ft.Text("Generated subtitles + audio will appear here.", size=12, color=ft.Colors.OUTLINE),
    ], spacing=6)
    results_col = ft.Column([
        ft.Text("Your final lyrics nightcore video will appear here.", size=12, color=ft.Colors.OUTLINE),
    ], spacing=8)

    audio_picker = ft.FilePicker()
    image_picker = ft.FilePicker()
    save_picker = ft.FilePicker()
    page.services.append(audio_picker)
    page.services.append(image_picker)
    page.services.append(save_picker)

    def _on_mode_change(e: ft.ControlEvent) -> None:
        flow["song_mode"] = mode_radio.value
        generate_only = flow["song_mode"] == "generate"
        for c in (gen_mode_radio, prompt_field, gen_lyrics_field, gen_instrumental_checkbox,
                  gen_thinking_checkbox, gen_language_dropdown, gen_seed_field, duration_slider):
            c.disabled = not generate_only
        for c in (asset_dropdown, existing_lyrics_field):
            c.disabled = generate_only
        if generate_only:
            _on_gen_mode_change(None)
        page.update()

    mode_radio.on_change = _on_mode_change

    def _on_gen_mode_change(e: ft.ControlEvent | None) -> None:
        gemma_mode = gen_mode_radio.value == "gemma"
        lyrics_needed = gen_mode_radio.value == "manual" and not gen_instrumental_checkbox.value
        gen_lyrics_field.disabled = not lyrics_needed or flow["song_mode"] != "generate"
        gen_instrumental_checkbox.disabled = gemma_mode or flow["song_mode"] != "generate"
        prompt_field.hint_text = ("e.g. a happy upbeat song about summer love" if gemma_mode
                                   else "e.g. upbeat synth-pop, female vocals, energetic")
        if e is not None:
            page.update()

    gen_mode_radio.on_change = _on_gen_mode_change
    gen_instrumental_checkbox.on_change = _on_gen_mode_change

    def _refresh_audio_assets(e: ft.ControlEvent | None = None) -> None:
        assets = list_audio_assets(JOBS_DIR)
        asset_dropdown.options = [ft.DropdownOption(str(a.path), text=a.label) for a in assets]
        page.update()

    def _refresh_image_assets(e: ft.ControlEvent | None = None) -> None:
        assets = list_image_assets(JOBS_DIR)
        image_dropdown.options = [ft.DropdownOption(str(a.path), text=a.label) for a in assets]
        page.update()

    def _on_duration_change(e: ft.ControlEvent) -> None:
        duration_label.value = f"Duration: {int(duration_slider.value)}s"
        page.update()

    duration_slider.on_change = _on_duration_change

    def _on_asset_pick(e: ft.ControlEvent) -> None:
        if asset_dropdown.value:
            flow["existing_song_path"] = Path(asset_dropdown.value)
            existing_song_label.value = f"Using: {Path(asset_dropdown.value).name}"
            page.update()

    asset_dropdown.on_change = _on_asset_pick

    async def _upload_song(e: ft.ControlEvent) -> None:
        files = await audio_picker.pick_files(
            dialog_title="Upload a song",
            allowed_extensions=[ext.lstrip(".") for ext in AUDIO_EXTENSIONS],
            file_type=ft.FilePickerFileType.CUSTOM, with_data=True,
        )
        if not files:
            return
        f = files[0]
        ext = Path(f.name).suffix.lower()
        if ext not in AUDIO_EXTENSIONS:
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
        flow["existing_song_path"] = dest
        existing_song_label.value = f"Using: {f.name}"
        page.update()

    def _on_image_source_change(e: ft.ControlEvent) -> None:
        picking = image_source_radio.value == "pick"
        image_dropdown.disabled = not picking
        upload_image_button.disabled = not picking
        page.update()

    image_source_radio.on_change = _on_image_source_change

    def _on_image_asset_pick(e: ft.ControlEvent) -> None:
        if image_dropdown.value:
            flow["image_path"] = Path(image_dropdown.value)
            image_label.value = f"Background: {Path(image_dropdown.value).name}"
            page.update()

    image_dropdown.on_change = _on_image_asset_pick

    async def _upload_image(e: ft.ControlEvent) -> None:
        files = await image_picker.pick_files(
            dialog_title="Pick a background image",
            allowed_extensions=[ext.lstrip(".") for ext in IMAGE_EXTENSIONS],
            file_type=ft.FilePickerFileType.CUSTOM, with_data=True,
        )
        if not files:
            return
        f = files[0]
        ext = Path(f.name).suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
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
        flow["image_path"] = dest
        image_label.value = f"Background set: {f.name}"
        page.update()

    upload_image_button.on_click = _upload_image

    # ---- save helpers --------------------------------------------------------------
    async def _save_artifact(src: Path, suggested_name: str) -> None:
        if flow["output_dir"]:
            dest = flow["output_dir"] / suggested_name
            shutil.copy(src, dest)
            notify(page, f"Saved to {dest}")
            return
        dest = await save_picker.save_file(dialog_title="Save a copy", file_name=suggested_name)
        if dest:
            shutil.copy(src, dest)
            notify(page, f"Saved to {dest}")

    def _save_artifact_handler(src: Path, suggested_name: str):
        async def _handler(e: ft.ControlEvent) -> None:
            await _save_artifact(src, suggested_name)
        return _handler

    def _run(e: ft.ControlEvent) -> None:
        if flow["busy"] or is_job_running():
            notify(page, "Something is already running.", warning=True)
            return
        mode = mode_radio.value
        if mode == "generate" and not (prompt_field.value or "").strip():
            notify(page, "Describe the song you want first.", warning=True)
            return
        if mode == "existing" and flow["existing_song_path"] is None:
            notify(page, "Pick or upload a song first.", warning=True)
            return

        seed_text = (gen_seed_field.value or "").strip()
        seed_value: int | None = None
        if seed_text:
            try:
                seed_value = int(seed_text)
            except ValueError:
                notify(page, "Seed must be a whole number, or left blank.", warning=True)
                return
        gen_options = {
            "sample_mode": gen_mode_radio.value == "auto",
            "write_with_gemma": gen_mode_radio.value == "gemma",
            "vocal_language": gen_language_dropdown.value or "unknown",
            "instrumental": gen_instrumental_checkbox.value,
            "thinking": gen_thinking_checkbox.value,
            "seed": seed_value,
        }

        flow["busy"] = True
        flow["rendered"] = False
        flow["stage_started_at"] = None
        flow["gen_progress_text"] = None
        flow["error_message"] = None
        flow["pipeline_returncode"] = None
        flow["render_returncode"] = None
        generated_col.controls = [ft.Text("Running...", size=12, color=ft.Colors.OUTLINE)]
        results_col.controls = [ft.Text("Running...", size=12, color=ft.Colors.OUTLINE)]

        threading.Thread(
            target=pipeline.run_all,
            args=(flow, mode, (prompt_field.value or "").strip(), (gen_lyrics_field.value or "").strip(),
                  float(duration_slider.value), gen_options, flow["existing_song_path"],
                  (existing_lyrics_field.value or "").strip(), image_source_radio.value, flow["image_path"]),
            daemon=True,
        ).start()
        status_label.value = "Starting..."
        page.update()

    run_button.on_click = _run

    async def _save_video(e: ft.ControlEvent) -> None:
        await _save_artifact(flow["video_out"], flow["video_out"].name)

    async def _save_audio(e: ft.ControlEvent) -> None:
        await _save_artifact(flow["audio_out"], flow["audio_out"].name)

    def _render_done_results() -> None:
        out_dir = flow["job_dir"] / "out"
        stem = flow["song_path"].stem
        gen_rows: list[ft.Control] = [ft.Text("Generated", weight=ft.FontWeight.BOLD)]
        gen_rows.append(ft.Text("Vocals separated (Demucs) + transcribed/aligned (WhisperX).",
                                 size=12, color=ft.Colors.OUTLINE))
        for ext, fname, label in _SUBTITLE_OUTPUTS:
            path = out_dir / fname
            if path.exists():
                gen_rows.append(ft.OutlinedButton(label, icon=ft.Icons.SAVE_ALT,
                                                   on_click=_save_artifact_handler(path, f"{stem}.{ext}")))
        generated_col.controls = gen_rows

        results_col.controls = [
            ft.Container(
                fv.Video(playlist=[fv.VideoMedia(resource=str(flow["video_out"]))], autoplay=False, expand=True),
                height=360,
            ),
            ft.Row([
                ft.FilledTonalButton("Save video", icon=ft.Icons.SAVE_ALT, on_click=_save_video),
                ft.OutlinedButton("Save audio only", icon=ft.Icons.AUDIOTRACK, on_click=_save_audio),
            ], spacing=8),
        ]

    def _render_error_results() -> None:
        generated_col.controls = [ft.Text(flow.get("error_message") or "Failed.", color=ft.Colors.ERROR)]
        results_col.controls = [ft.Text("Nothing to show — see above.", size=12, color=ft.Colors.OUTLINE)]

    def _poll() -> None:
        stage = flow.get("stage")
        if stage in pipeline.STAGE_TEXT:
            text = pipeline.STAGE_TEXT[stage]
            if stage == "gen_generating" and flow.get("gen_progress_text"):
                text = f"{text} — {flow['gen_progress_text']}"
            started_at = flow.get("stage_started_at")
            if started_at is not None:
                elapsed = int(time.monotonic() - started_at)
                text = f"{text} ({elapsed // 60}m {elapsed % 60:02d}s elapsed)"
            status_label.value = text
        elif stage in ("done", "error") and not flow["rendered"]:
            flow["rendered"] = True
            if stage == "done":
                status_label.value = "Done."
                _render_done_results()
            else:
                status_label.value = flow.get("error_message") or "Failed."
                _render_error_results()

        run_button.disabled = flow["busy"] or is_job_running()
        page.update()

    start_poll(page, active_token, 1.0, _poll)
    _refresh_audio_assets()
    _refresh_image_assets()
    _on_mode_change(None)

    return ft.Column([
        ft.Card(content=ft.Container(
            ft.Column([
                ft.Text("Output folder", weight=ft.FontWeight.BOLD),
                ft.Row([ft.OutlinedButton("Choose folder", icon=ft.Icons.FOLDER_OPEN, on_click=_pick_output_dir)]),
                output_dir_label,
            ], spacing=8),
            padding=16,
        )),
        ft.Card(content=ft.Container(
            ft.Column([
                ft.Text("1. Song", weight=ft.FontWeight.BOLD),
                mode_radio,
                ft.Divider(),
                gen_mode_radio,
                prompt_field, gen_lyrics_field,
                ft.Row([gen_instrumental_checkbox, gen_thinking_checkbox]),
                ft.Row([gen_language_dropdown, gen_seed_field], spacing=12),
                duration_slider, duration_label,
                ft.Divider(),
                asset_dropdown,
                ft.Row([
                    ft.OutlinedButton("Refresh list", icon=ft.Icons.REFRESH, on_click=_refresh_audio_assets),
                    ft.OutlinedButton("Upload new", icon=ft.Icons.UPLOAD_FILE, on_click=_upload_song),
                ], spacing=8),
                existing_lyrics_field,
                existing_song_label,
            ], spacing=10),
            padding=16,
        )),
        ft.Card(content=ft.Container(
            ft.Column([
                ft.Text("2. Background image", weight=ft.FontWeight.BOLD),
                image_source_radio,
                image_dropdown,
                upload_image_button,
                image_label,
            ], spacing=10),
            padding=16,
        )),
        ft.Card(content=ft.Container(
            ft.Column([run_button, status_label], spacing=8),
            padding=16,
        )),
        ft.Card(content=ft.Container(generated_col, padding=16)),
        ft.Card(content=ft.Container(results_col, padding=16)),
    ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)
