"""Generate Subtitles view — pick a song (+ optional lyrics) with native file
dialogs, run the pipeline (`aisongtool run`), save copies of the resulting
subtitle files wherever the user wants."""
from __future__ import annotations

import re
import shutil
import sys
import uuid
import zipfile
from pathlib import Path

import flet as ft

from .. import jobs
from ..notify import notify
from ..polling import start_poll
from ..state import JOBS_DIR, is_job_running

_WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo"]
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
_MAX_LYRICS_CHARS = 50_000

_DOWNLOADS = [
    ("srt", "final.srt", "Subtitles (.srt)"),
    ("ass", "final.ass", "Styled (.ass)"),
    ("vtt", "final.vtt", "Web (.vtt)"),
    ("lrc", "final.lrc", "Music player (.lrc)"),
    ("sbv", "final.sbv", "YouTube (.sbv)"),
    ("lyrics_clean.txt", "lyrics_clean.txt", "Cleaned lyrics (.txt)"),
]


def _safe_name(name: str | None) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", (name or "").strip())
    return name[:120] if name else "upload"


def _zip_outputs(out_dir: Path, stem: str) -> Path:
    zip_path = out_dir / "outputs.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for _, fname, _ in _DOWNLOADS:
            p = out_dir / fname
            if p.exists():
                z.write(p, arcname=f"{stem}_{fname}" if fname != "lyrics_clean.txt" else fname)
        log_p = out_dir / "pipeline.log"
        if log_p.exists():
            z.write(log_p, arcname="pipeline.log")
    return zip_path


def build(page: ft.Page, active_token: dict) -> ft.Control:
    job = {"job_dir": None, "out_dir": None, "song_path": None, "stem": "captions", "returncode": None}

    status_label = ft.Text("Pick a song to begin.", size=12, color=ft.Colors.OUTLINE)
    lyrics_box = ft.TextField(label="Lyrics (optional)", multiline=True, min_lines=8, max_lines=8,
                               hint_text="Paste lyrics here, or leave empty to transcribe only.")
    model_dropdown = ft.Dropdown(label="Whisper model", value="large-v3",
                                  options=[ft.DropdownOption(m) for m in _WHISPER_MODELS])
    language_field = ft.TextField(label="Language code (empty = auto)")
    vad_dropdown = ft.Dropdown(label="VAD backend", value="silero",
                                options=[ft.DropdownOption("silero"), ft.DropdownOption("pyannote")])
    segment_switch = ft.Switch(label="Segment mode (one cue per verse/chorus)", value=False)
    skip_demucs_switch = ft.Switch(label="Skip vocal separation (use raw audio)", value=False)
    run_button = ft.FilledButton("Generate", icon=ft.Icons.PLAY_ARROW, disabled=True)
    song_label = ft.Text("No song selected.", size=12, color=ft.Colors.OUTLINE)

    results_col = ft.Column([
        ft.Text("Outputs", weight=ft.FontWeight.BOLD),
        ft.Text("Downloads appear here once a run finishes.", size=12, color=ft.Colors.OUTLINE),
    ], spacing=8)

    song_picker = ft.FilePicker()
    save_picker = ft.FilePicker()
    page.services.append(song_picker)
    page.services.append(save_picker)

    async def _pick_song(e: ft.ControlEvent) -> None:
        files = await song_picker.pick_files(
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

        job_id = uuid.uuid4().hex[:12]
        job_dir = JOBS_DIR / job_id
        (job_dir / "input").mkdir(parents=True, exist_ok=True)
        (job_dir / "out").mkdir(parents=True, exist_ok=True)

        song_name = _safe_name(f.name)
        song_path = job_dir / "input" / song_name
        if f.path:
            shutil.copy(f.path, song_path)
        elif f.bytes:
            song_path.write_bytes(f.bytes)
        else:
            notify(page, "Could not read the picked file.", error=True)
            return

        job["job_dir"] = job_dir
        job["out_dir"] = job_dir / "out"
        job["song_path"] = song_path
        job["stem"] = Path(song_name).stem
        job["returncode"] = None
        song_label.value = f"Loaded {song_name}."
        run_button.disabled = False
        status_label.value = "Set options and click Generate."
        page.update()

    def _run(e: ft.ControlEvent) -> None:
        if job["song_path"] is None:
            notify(page, "Pick a song first.", warning=True)
            return
        if is_job_running():
            notify(page, "A job is already running.", warning=True)
            return
        lyrics = lyrics_box.value or ""
        if len(lyrics) > _MAX_LYRICS_CHARS:
            notify(page, f"Lyrics too long (max {_MAX_LYRICS_CHARS:,} characters).", error=True)
            return

        job_dir: Path = job["job_dir"]
        lyrics_path: Path | None = None
        if lyrics.strip():
            lyrics_path = job_dir / "input" / "lyrics.txt"
            lyrics_path.write_text(lyrics, encoding="utf-8")

        cmd = [
            sys.executable, "-m", "aisongtool.cli", "run",
            "--song", str(job["song_path"]),
            "--out", str(job["out_dir"]),
            "--whisper_model", model_dropdown.value,
            "--vad", vad_dropdown.value,
        ]
        if lyrics_path is not None:
            cmd += ["--lyrics", str(lyrics_path)]
        if (language_field.value or "").strip():
            cmd += ["--language", language_field.value.strip()]
        if segment_switch.value:
            cmd += ["--segment_mode"]
        if skip_demucs_switch.value:
            cmd += ["--skip_demucs"]

        job["returncode"] = None

        def _on_exit(code: int) -> None:
            job["returncode"] = code

        jobs.spawn_cli(cmd, cwd=job_dir, on_exit=_on_exit)
        status_label.value = "Running... see the Terminal tab for live output."
        page.update()

    run_button.on_click = _run

    def _save_copy_handler(src: Path, suggested_name: str):
        async def _handler(e: ft.ControlEvent) -> None:
            dest = await save_picker.save_file(dialog_title="Save a copy", file_name=suggested_name)
            if dest:
                shutil.copy(src, dest)
                notify(page, f"Saved to {dest}")
        return _handler

    def _poll() -> None:
        if job["out_dir"] is None:
            return
        running = is_job_running()
        out_dir: Path = job["out_dir"]
        stem = job["stem"]

        run_button.disabled = running or job["song_path"] is None
        if running:
            status_label.value = "Running... see the Terminal tab for live output."
            page.update()
            return

        if job["returncode"] is None:
            page.update()
            return  # never started, or already reported

        rows: list[ft.Control] = [ft.Text("Outputs", weight=ft.FontWeight.BOLD)]
        if job["returncode"] != 0 or not (out_dir / "final.srt").exists():
            rows.append(ft.Text("Job failed — check the Terminal tab for details.", color=ft.Colors.ERROR))
        else:
            status_label.value = "Done."
            for ext, fname, label in _DOWNLOADS:
                path = out_dir / fname
                if path.exists():
                    dl_name = f"{stem}.{ext}" if "." not in ext else fname
                    rows.append(ft.OutlinedButton(label, icon=ft.Icons.SAVE_ALT,
                                                   on_click=_save_copy_handler(path, dl_name)))
            zip_path = _zip_outputs(out_dir, stem)
            rows.append(ft.FilledTonalButton("Save all (.zip)", icon=ft.Icons.FOLDER_ZIP,
                                              on_click=_save_copy_handler(zip_path, f"{stem}_outputs.zip")))
        results_col.controls = rows
        job["returncode"] = None  # rendered once; avoid rebuilding every poll
        page.update()

    start_poll(page, active_token, 1.0, _poll)

    left_card = ft.Card(content=ft.Container(
        ft.Column([
            ft.Text("1. Pick a song", weight=ft.FontWeight.BOLD),
            ft.FilledButton("Choose song file", icon=ft.Icons.UPLOAD_FILE, on_click=_pick_song),
            song_label,
            ft.Text("2. Lyrics", weight=ft.FontWeight.BOLD),
            lyrics_box,
            ft.Text("3. Options", weight=ft.FontWeight.BOLD),
            model_dropdown,
            language_field,
            vad_dropdown,
            segment_switch,
            skip_demucs_switch,
            run_button,
            status_label,
        ], spacing=12, scroll=ft.ScrollMode.AUTO),
        padding=16, width=420,
    ))

    right_card = ft.Card(content=ft.Container(results_col, padding=16, expand=True))

    return ft.Row([left_card, right_card], spacing=16, expand=True, vertical_alignment=ft.CrossAxisAlignment.START)
