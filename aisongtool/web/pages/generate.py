"""Generate Subtitles tab — upload a song (+ optional lyrics), run the
pipeline (`aisongtool run`), download the resulting subtitle files."""
from __future__ import annotations

import re
import sys
import uuid
import zipfile
from pathlib import Path

from nicegui import events, ui

from .. import jobs
from ..state import JOBS_DIR, is_job_running

_WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo"]
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
_MAX_UPLOAD_BYTES = 200 * 1024 * 1024
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


def render() -> None:
    job = {"job_dir": None, "out_dir": None, "song_path": None, "stem": "captions", "returncode": None}

    with ui.row().classes("w-full gap-6 no-wrap items-start"):
        with ui.column().classes("w-96 gap-2"):
            ui.label("1. Upload song").classes("text-bold")
            upload = ui.upload(label="Song file (mp3/wav/m4a/...)", auto_upload=True,
                                max_file_size=_MAX_UPLOAD_BYTES).classes("w-full") \
                .props('accept=".mp3,.wav,.m4a,.aac,.flac,.ogg,.opus"')

            ui.label("2. Lyrics (optional)").classes("text-bold q-mt-md")
            lyrics_box = ui.textarea(placeholder="Paste lyrics here, or leave empty to transcribe only.") \
                .classes("w-full").props("rows=8 outlined")

            ui.label("3. Options").classes("text-bold q-mt-md")
            model_select = ui.select(_WHISPER_MODELS, value="large-v3", label="Whisper model").classes("w-full")
            language_input = ui.input(label="Language code (empty = auto)").classes("w-full")
            vad_select = ui.select(["silero", "pyannote"], value="silero", label="VAD backend").classes("w-full")
            segment_checkbox = ui.checkbox("Segment mode (one cue per verse/chorus)")
            skip_demucs_checkbox = ui.checkbox("Skip vocal separation (use raw audio)")

            run_button = ui.button("Generate", icon="play_arrow").classes("w-full q-mt-md")
            status_label = ui.label("Upload a song to begin.").classes("text-grey q-mt-sm")

        with ui.column().classes("flex-1 gap-2") as results_col:
            ui.label("Outputs").classes("text-bold")
            ui.label("Downloads appear here once a run finishes.").classes("text-grey")

    async def _on_upload(e: events.UploadEventArguments) -> None:
        f = e.file
        ext = Path(f.name).suffix.lower()
        if ext not in _AUDIO_EXTENSIONS:
            ui.notify(f"Unsupported file type '{ext}'.", type="negative")
            return
        if f.size() == 0:
            ui.notify("Uploaded file is empty.", type="negative")
            return

        job_id = uuid.uuid4().hex[:12]
        job_dir = JOBS_DIR / job_id
        (job_dir / "input").mkdir(parents=True, exist_ok=True)
        (job_dir / "out").mkdir(parents=True, exist_ok=True)

        song_name = _safe_name(f.name)
        song_path = job_dir / "input" / song_name
        await f.save(song_path)

        job["job_dir"] = job_dir
        job["out_dir"] = job_dir / "out"
        job["song_path"] = song_path
        job["stem"] = Path(song_name).stem
        job["returncode"] = None
        status_label.set_text(f"Loaded {song_name}. Set options and click Generate.")

    upload.on_upload(_on_upload)

    def _run() -> None:
        if job["song_path"] is None:
            ui.notify("Upload a song first.", type="warning")
            return
        if is_job_running():
            ui.notify("A job is already running.", type="warning")
            return
        lyrics = lyrics_box.value or ""
        if len(lyrics) > _MAX_LYRICS_CHARS:
            ui.notify(f"Lyrics too long (max {_MAX_LYRICS_CHARS:,} characters).", type="negative")
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
            "--whisper_model", model_select.value,
            "--vad", vad_select.value,
        ]
        if lyrics_path is not None:
            cmd += ["--lyrics", str(lyrics_path)]
        if language_input.value.strip():
            cmd += ["--language", language_input.value.strip()]
        if segment_checkbox.value:
            cmd += ["--segment_mode"]
        if skip_demucs_checkbox.value:
            cmd += ["--skip_demucs"]

        job["returncode"] = None

        def _on_exit(code: int) -> None:
            job["returncode"] = code

        jobs.spawn_cli(cmd, cwd=job_dir, on_exit=_on_exit)
        status_label.set_text("Running... see the Terminal tab for live output.")

    run_button.on_click(_run)

    def _poll() -> None:
        if job["out_dir"] is None:
            return
        running = is_job_running()
        out_dir: Path = job["out_dir"]
        stem = job["stem"]

        if running:
            run_button.props("loading")
            status_label.set_text("Running... see the Terminal tab for live output.")
            return

        run_button.props(remove="loading")
        if job["returncode"] is None:
            return  # never started, or already reported

        results_col.clear()
        with results_col:
            ui.label("Outputs").classes("text-bold")
            if job["returncode"] != 0 or not (out_dir / "final.srt").exists():
                ui.label("Job failed — check the Terminal tab for details.").classes("text-negative")
            else:
                status_label.set_text("Done.")
                for ext, fname, label in _DOWNLOADS:
                    path = out_dir / fname
                    if path.exists():
                        dl_name = f"{stem}.{ext}" if "." not in ext else fname
                        ui.button(label, icon="download", on_click=lambda p=path, n=dl_name: ui.download(p, filename=n))
                zip_button = ui.button("Download all (.zip)", icon="folder_zip")
                zip_button.on_click(lambda: ui.download(_zip_outputs(out_dir, stem), filename=f"{stem}_outputs.zip"))
        job["returncode"] = None  # rendered once; avoid rebuilding every poll

    ui.timer(1.0, _poll)
